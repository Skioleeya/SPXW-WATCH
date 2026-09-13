/* WebGL 热力图渲染引擎
 * ------------------------------------------------------------------
 * 原生 WebGL，无外部依赖。职责单一：在 canvas 上绘制热力图格子。
 *
 * 数据通过 RGBA texture 上传：
 *   R = 值（归一化到 [-1, 1] 后映射到 [0, 255]）
 *   G = 有效标志（255 = 有数据，0 = 空值）
 *   B/A = 未使用
 *
 * 调色板用 Turbo colormap，作为 15×1 的 RGB texture。
 *
 * Fragment Shader 用 UV 坐标直接映射到格子索引，空值输出背景色。
 * 全屏一个 draw call，GPU 并行填充所有像素。
 * ------------------------------------------------------------------ */
(function(global) {
  "use strict";

  /* Turbo colormap (15 colors × 3 bytes, bottom→top) */
  var TURBO = new Uint8Array([
    48, 18, 59,    65, 69, 171,   70, 117, 237,   57, 162, 252,
    27, 207, 212,  36, 236, 166,  97, 252, 108,  164, 252, 59,
    209, 232, 52,  243, 198, 58,  254, 155, 45,  243, 99, 21,
    217, 56, 6,    177, 25, 1,    122, 4, 2
  ]);

  var VS =
    "attribute vec2 a_pos;" +
    "varying vec2 v_uv;" +
    "void main(){" +
    "  v_uv=a_pos*0.5+0.5;" +
    "  gl_Position=vec4(a_pos,0.0,1.0);" +
    "}";

  var FS =
    "precision mediump float;" +
    "uniform sampler2D u_data;" +
    "uniform sampler2D u_palette;" +
    "uniform vec4 u_bg;" +
    "uniform vec4 u_grid;" +
    "uniform vec2 u_cells;" +
    "uniform float u_volMax;" +
    "varying vec2 v_uv;" +
    "void main(){" +
    "  if(v_uv.x<u_grid.x||v_uv.x>u_grid.z||v_uv.y<u_grid.w||v_uv.y>u_grid.y){" +
    "    gl_FragColor=u_bg;return;" +
    "  }" +
    "  float gw=u_grid.z-u_grid.x;" +
    "  float gh=u_grid.y-u_grid.w;" +
    "  if(gw<=0.0||gh<=0.0){gl_FragColor=u_bg;return;}" +
    "  float col=clamp(floor((v_uv.x-u_grid.x)/gw*u_cells.x),0.0,u_cells.x-1.0);" +
    "  float row=clamp(floor((u_grid.y-v_uv.y)/gh*u_cells.y),0.0,u_cells.y-1.0);" +
    "  vec2 dUv=vec2((col+0.5)/u_cells.x,(row+0.5)/u_cells.y);" +
    "  vec4 s=texture2D(u_data,dUv);" +
    "  if(s.g<0.5){gl_FragColor=u_bg;return;}" +
    "  float t=clamp(s.r*0.5+0.5,0.0,1.0);" +
    "  vec4 color=texture2D(u_palette,vec2(t,0.5));" +
    "  float vol=s.b/255.0;" +
    "  if(vol>0.0&&u_volMax>0.0){" +
    "    float cellW=gw/u_cells.x;" +
    "    float cellH=gh/u_cells.y;" +
    "    float cellLeft=u_grid.x+col*cellW;" +
    "    float cellTop=u_grid.y-row*cellH;" +
    "    float localX=(v_uv.x-cellLeft)/cellW;" +
    "    float localY=(cellTop-v_uv.y)/cellH;" +
    "    float border=vol*0.35;" +
    "    if(localX<border||localX>1.0-border||localY<border||localY>1.0-border){" +
    "      color=mix(color,vec4(1.0,1.0,1.0,color.a),0.6);" +
    "    }" +
    "  }" +
    "  gl_FragColor=color;" +
    "}";

  function compile(gl, type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      throw new Error("Shader compile: " + gl.getShaderInfoLog(s));
    }
    return s;
  }

  function GlHeatmap(canvas) {
    this._canvas = canvas;
    var gl = canvas.getContext("webgl", { alpha: false, antialias: false });
    if (!gl) throw new Error("WebGL not available");
    this._gl = gl;

    var prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error("Program link: " + gl.getProgramInfoLog(prog));
    }
    gl.useProgram(prog);

    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
      -1,-1, 1,-1, -1,1,
      -1,1,  1,-1,  1,1
    ]), gl.STATIC_DRAW);
    var aPos = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    this._loc = {
      data: gl.getUniformLocation(prog, "u_data"),
      palette: gl.getUniformLocation(prog, "u_palette"),
      bg: gl.getUniformLocation(prog, "u_bg"),
      grid: gl.getUniformLocation(prog, "u_grid"),
      cells: gl.getUniformLocation(prog, "u_cells"),
      volMax: gl.getUniformLocation(prog, "u_volMax")
    };

    var pal = gl.createTexture();
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, pal);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, 15, 1, 0, gl.RGB, gl.UNSIGNED_BYTE, TURBO);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.uniform1i(this._loc.palette, 1);

    this._dataTex = null;
  }

  GlHeatmap.prototype.resize = function(w, h) {
    var c = this._canvas;
    var dpr = global.devicePixelRatio || 1;
    c.width = Math.floor(w * dpr);
    c.height = Math.floor(h * dpr);
    c.style.width = w + "px";
    c.style.height = h + "px";
    this._gl.viewport(0, 0, c.width, c.height);
  };

  GlHeatmap.prototype.setGrid = function(left, top, right, bottom) {
    this._gl.uniform4f(this._loc.grid, left, top, right, bottom);
  };

  GlHeatmap.prototype.setBg = function(r, g, b, a) {
    this._gl.uniform4f(this._loc.bg, r, g, b, a);
  };

  GlHeatmap.prototype.update = function(rows, cols, values, vmax, volumes) {
    var gl = this._gl;
    var pixels = new Uint8Array(rows * cols * 4);

    /* 计算 volume 最大值用于归一化 */
    var volMax = 0;
    if (volumes && volumes.length) {
      for (var r = 0; r < rows; r++) {
        var vrow = volumes[r] || [];
        for (var c = 0; c < cols; c++) {
          var vc = vrow[c];
          if (vc !== null && vc !== undefined && vc > volMax) volMax = vc;
        }
      }
    }

    for (var r = 0; r < rows; r++) {
      var row = values[r] || [];
      var vrow = volumes && volumes[r] ? volumes[r] : [];
      /* inverse Y: high strike at top → reverse texture row order */
      var tr = rows - 1 - r;
      for (var c = 0; c < cols; c++) {
        var v = row[c];
        var i = (tr * cols + c) * 4;
        if (v === null || v === undefined) {
          pixels[i] = 0; pixels[i+1] = 0; pixels[i+2] = 0; pixels[i+3] = 0;
        } else {
          var norm = Math.max(-1, Math.min(1, v / vmax));
          pixels[i] = Math.floor((norm * 0.5 + 0.5) * 255);
          pixels[i+1] = 255;
          /* B 通道 = volume 强度（0–255），无 volume 时填 0 */
          var vc = vrow[c];
          pixels[i+2] = (volMax > 0 && vc !== null && vc !== undefined)
            ? Math.floor((vc / volMax) * 255) : 0;
          pixels[i+3] = 255;
        }
      }
    }

    if (!this._dataTex) {
      this._dataTex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this._dataTex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    }
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this._dataTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, cols, rows, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    gl.uniform1i(this._loc.data, 0);
    gl.uniform2f(this._loc.cells, cols, rows);
    gl.uniform1f(this._loc.volMax, volMax > 0 ? 1.0 : 0.0);
  };

  GlHeatmap.prototype.render = function() {
    this._gl.drawArrays(this._gl.TRIANGLES, 0, 6);
  };

  global.GlHeatmap = GlHeatmap;
})(window);
