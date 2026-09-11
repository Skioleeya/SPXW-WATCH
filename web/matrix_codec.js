/* 热力图数值块解码器
 * ------------------------------------------------------------------
 * 职责单一：把帧里的 [位图][定标整数] 还原成 block.values（二维数组）。
 *
 * 为什么在前端解、而不是让后端发二维数组：矩阵里约 88% 的格子是空的，
 * JSON 每个空格至少要写 5 个字节（null,），实测占整帧 71%。改成位图 +
 * 定标整数后，在 permessage-deflate 之上再省 87%。**语义完全不变** ——
 * 位图的 0 位等价于原来的 null（"还没到那个时间桶"），不是 0。
 *
 * 逐位约定必须与 serialization/bitmap_codec.py 一致，由
 * tools/check_matrix_codec.py 逐值对拍（Python 打包 → Node 解包 → 比数）。
 *
 * 编码名从帧里的 enc 字段读，前端只实现这一种；名字对不上就直接报错并保留
 * 上一帧，绝不"猜一个格式继续画" —— 画错的热力图比空图更危险。
 * ------------------------------------------------------------------ */

(function (global) {
  "use strict";

  var NAME = "bm16";

  function fail(message) {
    if (global.console && console.error) {
      console.error("[matrix] " + message);
    }
  }

  function b64ToBytes(b64) {
    var bin = global.atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) { out[i] = bin.charCodeAt(i); }
    return out;
  }

  function decode(block) {
    if (!block) { return block; }
    if (block.values) { return block; }        /* 幂等：已解过直接返回 */
    /* 判"有没有"要用 undefined 比较，不能用真值判断 —— 空矩阵的 bm/i16 是
       空字符串，是 falsy，用真值判断会把合法的全空矩阵误判成"没有编码块"。 */
    if (block.bm === undefined || block.i16 === undefined) { return block; }

    if (block.enc !== NAME) {
      fail("未知的数值块编码 " + block.enc + "，本前端只认 " + NAME);
      return block;
    }

    var rows = Number(block.rows);
    var cols = Number(block.cols);
    var scale = Number(block.scale);
    if (!isFinite(rows) || !isFinite(cols) || rows < 0 || cols < 0 || !(scale > 0)) {
      fail("矩阵形状或定标非法：rows=" + block.rows + " cols=" + block.cols +
        " scale=" + block.scale);
      return block;
    }
    if (rows === 0 || cols === 0) {
      /* 链还没解析出来时矩阵是空的：合法的退化态，画空图而不是报错 */
      block.values = [];
      return block;
    }

    var bits, nums;
    try {
      bits = b64ToBytes(block.bm);
      nums = b64ToBytes(block.i16);
    } catch (e) {
      fail("base64 解码失败: " + e.message);
      return block;
    }

    var view = new DataView(nums.buffer, nums.byteOffset, nums.byteLength);
    var values = [];
    var k = 0;

    for (var r = 0; r < rows; r++) {
      var row = new Array(cols);
      var base = r * cols;
      for (var c = 0; c < cols; c++) {
        var i = base + c;
        if (bits[i >> 3] >> (7 - (i & 7)) & 1) {
          row[c] = view.getInt16(k * 2, true) / scale;
          k++;
        } else {
          row[c] = null;
        }
      }
      values.push(row);
    }

    var declared = view.byteLength / 2;
    if (k !== declared) {
      fail("位图置位数 " + k + " 与整数个数 " + declared +
        " 不一致，编码约定已分叉");
      return block;
    }
    if (k !== Number(block.filled)) {
      fail("还原出的格数 " + k + " 与帧声明的 filled " + block.filled + " 不一致");
      return block;
    }

    block.values = values;
    return block;
  }

  function decodeFrame(frame) {
    if (!frame) { return frame; }
    decode(frame.heatmap);
    return frame;
  }

  global.SWATCH_MATRIX = {
    NAME: NAME,
    decode: decode,
    decodeFrame: decodeFrame
  };
})(window);
