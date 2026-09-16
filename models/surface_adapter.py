"""
models/surface_adapter.py
==========================
L4 曲面模型对 L5 的出口：把原版 ``models/`` 的三个模型包装成 L0 的
``SurfaceModelPort``。

为什么要这一层
--------------
原版模型的公开接口是"pandas 进、pandas 出"—— ``surface()`` 返回 DataFrame、
``residuals()`` 返回 DataFrame、``diagnostics()`` 返回的字典里还塞着
``fit_summary``（DataFrame）和 ``svi_params``（ndarray）。如果让 L5 直接持有
模型对象，pandas/numpy 就顺着 ``residuals()`` 流进特征层，"数值库只允许出现在
models/ 层"这条约束当场失效，而且失效得无声无息（下游只是拿到一个对象）。

所以本模块干两件事：

1. 按 ``config/surface.json::active_model`` 选模型，名字写错**立刻抛错**
   （``contracts.enums.SurfaceModelName.parse()``），不静默退回 Raw；
2. 把 ``diagnostics()`` / ``residuals()`` 的 pandas 输出**翻译成 L0 的
   ``SurfaceSummary`` / ``SurfaceResidual``**（frozen dataclass + tuple）。
   L5 拿到的东西里没有任何 pandas 对象可用 —— 这是机械手段，不是约定。

与原版 ``surface_adapter.py`` 的关系
------------------------------------
原版那个文件是 Dash 过渡期的 shim（``build_surface_via_model(app)``），**已整体
删除**，因为它三处违反本项目规则：

* 读 CWD 下的 ``model_config.json``（配置不在 ``config/``，且路径依赖工作目录）；
* 模块导入时就 ``_model = create_active_model()``（导入副作用：import 一次就建模型）；
* 未知模型名 ``print`` 一句就退回 SVI（静默降级）。

本文件只沿用它的**职责位置**（L4 的出口适配器），不沿用实现。

遗留项
------
``summary().residuals`` 目前带上**全部**清洗后的点。L5/L6 把它放进帧时必须有
上限（每 400ms 推一次，几百个点会压过位图编码的热力图本身）。上限属于"上线格式"
的决策，等 L6 的载荷组装落地时连同配置键一起加，不在这里提前造一个没有消费方的键。
"""

from __future__ import annotations

from models.base_surface_model import BaseSurfaceModel
from models.raw_surface_model import RawSurfaceModel
from models.ssvi_surface_model import SSVISurfaceModel
from models.svi_surface_model import SVISurfaceModel
from models.svi_fit import svi_allowed_statuses
from models.surface_params import active_model_name

from contracts.enums import SurfaceModelName
from contracts.feature import SurfaceResidual, SurfaceSummary
from contracts.ports import SurfaceInputPort

# 模型名 → 实现类。这是**标准映射表**（领域结构不变量），不是可调参数：
# 三个类就是原版 models/ 的全部模型，加一个模型等于加一次实现。
_MODEL_REGISTRY: dict[SurfaceModelName, type[BaseSurfaceModel]] = {
    SurfaceModelName.RAW: RawSurfaceModel,
    SurfaceModelName.SVI: SVISurfaceModel,
    SurfaceModelName.SSVI: SSVISurfaceModel,
}


class SurfaceModelAdapter:
    """
    ``SurfaceModelPort`` 的实现。

    用法（组装层 L8）::

        adapter = SurfaceModelAdapter()          # 名字取自 config/surface.json
        adapter.fit(surface_input)               # surface_input 实现 SurfaceInputPort
        bundle.surface = adapter.summary()       # L5 只拿到 L0 类型
    """

    def __init__(self, model_name: SurfaceModelName | None = None) -> None:
        if model_name is None:
            model_name = SurfaceModelName.parse(active_model_name())

        self._kind = model_name
        self._model: BaseSurfaceModel = _MODEL_REGISTRY[model_name]()
        self._summary = SurfaceSummary(model_name=model_name.value)
        self._fitted = False

    # ------------------------------------------------------------------ #
    # SurfaceModelPort
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        """模型名（用于帧内标注）。"""
        return self._kind.value

    def fit(self, source: SurfaceInputPort) -> None:
        """
        按当前行情重新拟合。

        ``source`` 直接交给原版模型：``SurfaceInputPort`` 的 5 个属性
        （``iv_dict`` / ``id_map`` / ``quote_dict`` / ``spot_price`` /
        ``is_delayed``）就是从原版 ``models/`` 逐字核出的全部耦合面，形状一致，
        不需要中间对象。
        """
        self._model.fit(source)
        self._summary = self._build_summary()
        self._fitted = True

    def summary(self) -> SurfaceSummary:
        """拟合诊断 + 逐点残差，已翻译成 L0 类型（无 pandas/numpy 对象）。"""
        self._require_fit()
        return self._summary

    def iv(self, expiry: str, strike: float) -> float | None:
        """查询某个 (到期日, 行权价) 的模型 IV（小数）。"""
        self._require_fit()
        return self._model.iv(expiry, strike)

    # ------------------------------------------------------------------ #
    # 内部：翻译
    # ------------------------------------------------------------------ #

    def _require_fit(self) -> None:
        if not self._fitted:
            raise RuntimeError(
                "SurfaceModelAdapter.fit() 必须先调用才能读结果。"
            )

    def _build_summary(self) -> SurfaceSummary:
        diag = self._model.diagnostics()
        status_by_expiry = self._status_by_expiry()

        counts = self._counts(diag)
        avg_rmse, max_rmse = self._rmse_vol_points(diag)

        return SurfaceSummary(
            model_name=str(diag.get("model_name", self._kind.value)),
            fitted_expiries=counts[0],
            failed_expiries=counts[1],
            good_fits=counts[2],
            warn_fits=counts[3],
            bad_fits=counts[4],
            fallback_expiries=counts[5],
            avg_rmse_vol_points=avg_rmse,
            max_rmse_vol_points=max_rmse,
            residuals=self._residuals(status_by_expiry),
        )

    def _counts(self, diag: dict) -> tuple[int, int, int, int, int, int]:
        """
        返回 (fitted, failed, good, warn, bad, fallback)。

        三个模型的 ``diagnostics()`` 键并不一致 —— 原版就这么长的，本层不去
        统一它们（改模型层等于改拟合行为），只在这里做一次翻译。
        """
        expiries = int(diag.get("num_expiries", 0) or 0)

        if self._kind is SurfaceModelName.RAW:
            # Raw 没有参数拟合这一步：每个有数据的到期日都算"拟合成功"。
            return expiries, 0, 0, 0, 0, 0

        if self._kind is SurfaceModelName.SVI:
            return (
                int(diag.get("svi_fits_succeeded", 0) or 0),
                int(diag.get("svi_fits_failed", 0) or 0),
                int(diag.get("svi_good_fits", 0) or 0),
                int(diag.get("svi_warn_fits", 0) or 0),
                int(diag.get("svi_bad_fits", 0) or 0),
                int(diag.get("svi_fallback_fits", 0) or 0),
            )

        # SSVI：全局一次标定，所以"成功/失败"按到期日粒度展开。
        fitted = int(diag.get("ssvi_n_expiries_calibrated", 0) or 0)
        failed = max(expiries - fitted, 0)
        status = str(diag.get("fit_status", ""))
        return (
            fitted,
            failed,
            1 if status == "GOOD" else 0,
            1 if status == "WARN" else 0,
            1 if status == "BAD" else 0,
            failed,
        )

    def _rmse_vol_points(self, diag: dict) -> tuple[float | None, float | None]:
        """把 RMSE 换算成 vol points（模型层的 RMSE 是小数）。"""
        if self._kind is SurfaceModelName.RAW:
            return None, None

        if self._kind is SurfaceModelName.SVI:
            return _times_100(diag.get("avg_rmse")), _times_100(diag.get("max_rmse"))

        quality = _to_float(diag.get("fit_quality"))
        return quality, quality

    def _status_by_expiry(self) -> dict[str, str]:
        """
        ``{expiry: GOOD/WARN/BAD/FAIL}``。

        SVI 有逐到期日的 ``fit_summary()``；SSVI 只有全局一个状态，就摊到每个
        到期日；Raw 没有拟合，返回空表（残差恒为 0，状态无意义）。
        """
        if self._kind is SurfaceModelName.RAW:
            return {}

        if self._kind is SurfaceModelName.SSVI:
            status = str(self._model.diagnostics().get("fit_status", ""))
            frame = self._model.clean_df()
            if frame is None or frame.empty:
                return {}
            return {str(e): status for e in frame["Expiry"].unique()}

        summary = self._model.fit_summary()
        if summary is None or summary.empty:
            return {}
        return {
            str(row.Expiry): str(row.Status)
            for row in summary.itertuples(index=False)
        }

    def _residuals(self, status_by_expiry: dict[str, str]) -> tuple[SurfaceResidual, ...]:
        frame = self._model.residuals()
        if frame is None or frame.empty:
            return ()

        allowed = svi_allowed_statuses()
        out: list[SurfaceResidual] = []

        for row in frame.to_dict("records"):
            expiry = str(row.get("Expiry", ""))
            status = status_by_expiry.get(expiry, "")
            model_iv = _to_float(row.get("SurfaceIV"))

            out.append(
                SurfaceResidual(
                    expiry=expiry,
                    strike=float(row.get("Strike", 0.0)),
                    raw_iv=float(row.get("RawIV", 0.0)),
                    model_iv=model_iv,
                    residual_vol_points=_to_float(row.get("ResidualVol")),
                    fit_status=status,
                    used_fallback=bool(status) and status not in allowed,
                    # 方向：``clean_df`` 的 Right 列（本项目新增）。
                    # 缺列时退回空串而不是抛错 —— Raw 模型走 ``_raw`` 且没有
                    # 方向约束，强行要求它会让 Raw 模式整段消失。
                    right=str(row.get("Right", "") or ""),
                )
            )

        return tuple(out)


def _to_float(value: object) -> float | None:
    """把可能是 NaN / None / numpy 标量的值转成 ``float | None``。"""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out  # NaN != NaN


def _times_100(value: object) -> float | None:
    out = _to_float(value)
    return None if out is None else out * 100.0
