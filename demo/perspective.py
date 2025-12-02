# -*- coding: utf-8 -*-
"""
PySide6 + OpenGL 3.3 Core
固定视口白框 + 自动缩放补偿的“水平 / 垂直透视矫正” Demo

核心特性：
- 画布留白：图片只渲染在窗口中央的一个区域（默认 80%），四周是深灰背景。
- 固定白色边框：在屏幕空间绘制一个静止不动的白色取景框（不参与透视变形）。
- 透视矫正：在 fragment shader 中基于 vPos ([-1,1]^2) 做 keystone 风格变形。
- 自动缩放补偿：根据 uHorz / uVert 计算 uScale，保证白框内无黑边。

说明：
- 顶点的“逻辑坐标”始终在 [-1, 1] 范围；
- 用 uniform uFrameScale 控制 NDC 中的实际尺寸（例如 0.8 -> 80% 视口）；
- 纹理坐标通过 uScale 修正，避免因为透视压缩导致的采样越界。
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat, QAction, QImage
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QFileDialog
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from OpenGL.GL import *
from OpenGL.GL.shaders import compileShader, compileProgram


# 顶点着色器（图片层）：
# - aPos：逻辑坐标 [-1, 1]
# - uFrameScale：控制该矩形在 NDC 中实际占比（例如 0.8 -> 占用窗口 80%）
# - vPos：保留原始 [-1,1] 坐标给 fragment 做透视计算
VERT_SHADER_IMG = """
#version 330 core
layout(location=0) in vec2 aPos;

uniform float uFrameScale;  // 视口缩放（0~1）

out vec2 vPos;  // 逻辑坐标（始终在 [-1, 1]）

void main()
{
    // 顶点在 NDC 中只占据 [-uFrameScale, uFrameScale]
    vec2 p = aPos * uFrameScale;
    gl_Position = vec4(p, 0.0, 1.0);

    // vPos 保持逻辑 [-1,1]，与 uFrameScale 解耦
    vPos = aPos;
}
"""

# 片元着色器（图片层）：
# - 基于 vPos 做 keystone 风格透视
# - 使用 uScale 做自动缩放补偿，避免白框内出现纹理越界的黑边
FRAG_SHADER_IMG = """
#version 330 core
in vec2 vPos;
out vec4 FragColor;

uniform sampler2D uTex;
uniform float uHorz;    // 水平透视系数 [-1,1]
uniform float uVert;    // 垂直透视系数 [-1,1]
uniform float uScale;   // 自动缩放补偿系数 >= 1

void main()
{
    // vPos 是逻辑坐标，范围 [-1, 1]
    vec2 p = vPos;

    // keystone 风格透视：
    //  - uHorz：根据 y 对 x 做透视缩放（上窄下宽 / 上宽下窄）
    //  - uVert：根据 x 对 y 做透视缩放（左窄右宽 / 右窄左宽）
    float zx = 1.0 + uHorz * p.y;  // 水平“深度因子”
    float zy = 1.0 + uVert * p.x;  // 垂直“深度因子”

    // 避免除以 0
    zx = max(zx, 0.0001);
    zy = max(zy, 0.0001);

    // 透视逆变换 + 自动缩放补偿：
    // uScale 越大，采样坐标范围越小 -> 实际视觉上“放大 / 拉近”图像
    vec2 q;
    q.x = (p.x / zx) / uScale;
    q.y = (p.y / zy) / uScale;

    // q 仍在 [-1,1] 的一个子区间，映射到纹理坐标 [0,1]
    vec2 uv = q * 0.5 + 0.5;

    // 使用 CLAMP_TO_EDGE 避免越界拉出黑边
    // 若数值略微越界也会被贴图环绕模式夹在边缘像素
    FragColor = texture(uTex, uv);
}
"""

# 顶点着色器（白框层）：
# - 使用同一套顶点数据 aPos（[-1,1]）
# - 同样通过 uFrameScale 缩放到 NDC 中的矩形范围
VERT_SHADER_FRAME = """
#version 330 core
layout(location=0) in vec2 aPos;

uniform float uFrameScale;  // 视口缩放（与图片层一致）

void main()
{
    vec2 p = aPos * uFrameScale;
    gl_Position = vec4(p, 0.0, 1.0);
}
"""

# 片元着色器（白框层）：仅输出统一颜色
FRAG_SHADER_FRAME = """
#version 330 core
out vec4 FragColor;
uniform vec4 uColor;

void main()
{
    FragColor = uColor;
}
"""


class GLView(QOpenGLWidget):
    """
    支持图片导入 + 固定视口白框 + 自动缩放补偿透视矫正的最小 GL 视图
    """
    def __init__(self):
        super().__init__()
        # 着色器程序
        self.program_img = None   # 图片层
        self.program_frame = None # 白框层

        # 顶点对象
        self.vao = None
        self.vbo = None

        # 纹理
        self.texture = None
        self.img_qt: QImage | None = None
        self.tex_w = 1
        self.tex_h = 1

        # 透视参数
        self.uHorz = 0.0
        self.uVert = 0.0
        self.uScale = 1.0  # 自动缩放补偿

        # 视口（画布）缩放：取 0.8 即窗口中间 80% 区域为“白框 + 图片”区域
        self.frame_scale = 0.8

    # -------- 对外接口 --------
    def load_image(self, path: str):
        img = QImage(path)
        if img.isNull():
            print("读取失败：", path)
            return

        # 统一为 RGBA8888
        img = img.convertToFormat(QImage.Format_RGBA8888)
        self.img_qt = img
        self.tex_w, self.tex_h = img.width(), img.height()

        self.makeCurrent()
        self._upload_texture()
        self.doneCurrent()

        self.update()

    def set_horizontal_perspective(self, v: float):
        """v: -1.0 ~ 1.0"""
        self.uHorz = v
        self._update_scale()
        self.update()

    def set_vertical_perspective(self, v: float):
        """v: -1.0 ~ 1.0"""
        self.uVert = v
        self._update_scale()
        self.update()

    def _update_scale(self):
        """
        根据当前 uHorz / uVert 计算自动缩放补偿系数 uScale。

        推导思路（简化版）：
        - 对于 keystone 形式的 zx = 1 + uHorz * y, y ∈ [-1,1]
          其最小值为 1 - |uHorz|（|uHorz| < 1）。
        - 为确保 |q| = |p/z|/uScale <= 1，对最坏情况 p=1, z=1-|u| 有：
              1 / ((1 - |u|) * uScale) <= 1
          故有 uScale >= 1 / (1 - |u|)。
        - 同理对 uVert。
        - 综合两者，取：
              uScale = 1 / (1 - max(|uHorz|, |uVert|))
        """
        max_shear = max(abs(self.uHorz), abs(self.uVert))
        if max_shear < 1e-4:
            self.uScale = 1.0
        else:
            # 防止极端接近 1 导致爆炸
            max_shear = min(max_shear, 0.95)
            self.uScale = 1.0 / (1.0 - max_shear)

    # -------- OpenGL 生命周期 --------
    def initializeGL(self):
        glClearColor(0.1, 0.1, 0.12, 1.0)
        glDisable(GL_DEPTH_TEST)

        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # 编译着色器程序
        self.program_img = compileProgram(
            compileShader(VERT_SHADER_IMG, GL_VERTEX_SHADER),
            compileShader(FRAG_SHADER_IMG, GL_FRAGMENT_SHADER),
        )
        self.program_frame = compileProgram(
            compileShader(VERT_SHADER_FRAME, GL_VERTEX_SHADER),
            compileShader(FRAG_SHADER_FRAME, GL_FRAGMENT_SHADER),
        )

        # 顶点数据：逻辑坐标 [-1,1] 的矩形
        # 顶点顺序既能支持 TRIANGLE_STRIP 也能支持 LINE_LOOP (0,1,2,3)
        verts = [
            -1.0, -1.0,  # 0: 左下
             1.0, -1.0,  # 1: 右下
             1.0,  1.0,  # 2: 右上
            -1.0,  1.0,  # 3: 左上
        ]
        import array
        data = array.array("f", verts)

        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)

        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, len(data) * 4, data.tobytes(), GL_STATIC_DRAW)

        # layout(location=0) in vec2 aPos;
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 8, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)

        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

        # 创建纹理对象（真正数据在 load_image 时上传）
        self.texture = glGenTextures(1)

    def _upload_texture(self):
        if self.img_qt is None or not self.texture:
            return

        img = self.img_qt
        mv = img.bits()
        raw = mv.tobytes()  # RGBA8888

        glBindTexture(GL_TEXTURE_2D, self.texture)
        glTexImage2D(
            GL_TEXTURE_2D,
            0,
            GL_RGBA,
            img.width(),
            img.height(),
            0,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            raw,
        )
        # 线性过滤 + 边缘拉伸
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glBindTexture(GL_TEXTURE_2D, 0)

    def resizeGL(self, w: int, h: int):
        glViewport(0, 0, w, h)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT)

        if not (self.program_img and self.program_frame and self.vao and self.texture):
            return

        glBindVertexArray(self.vao)

        # ---------- 1) 绘制图片层（带透视 + 自动缩放补偿） ----------
        glUseProgram(self.program_img)

        # 绑定纹理到 0 号单元
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.texture)
        loc_tex = glGetUniformLocation(self.program_img, "uTex")
        glUniform1i(loc_tex, 0)

        # 设置透视参数 + 缩放补偿 + 视口缩放
        glUniform1f(glGetUniformLocation(self.program_img, "uHorz"), self.uHorz)
        glUniform1f(glGetUniformLocation(self.program_img, "uVert"), self.uVert)
        glUniform1f(glGetUniformLocation(self.program_img, "uScale"), self.uScale)
        glUniform1f(glGetUniformLocation(self.program_img, "uFrameScale"), self.frame_scale)

        # 使用 TRIANGLE_STRIP 画满“逻辑方形” [-1,1]（实际 NDC 里是缩小后的矩形）
        glDrawArrays(GL_TRIANGLE_FAN, 0, 4)

        # ---------- 2) 绘制固定白色边框（不参与透视） ----------
        glUseProgram(self.program_frame)
        glUniform1f(glGetUniformLocation(self.program_frame, "uFrameScale"), self.frame_scale)
        glUniform4f(glGetUniformLocation(self.program_frame, "uColor"), 1.0, 1.0, 1.0, 1.0)

        # 注意：不强行设置 glLineWidth，避免某些实现上 1.0 以外触发 INVALID_VALUE
        glDrawArrays(GL_LINE_LOOP, 0, 4)

        # 清理
        glBindVertexArray(0)
        glBindTexture(GL_TEXTURE_2D, 0)
        glUseProgram(0)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Perspective Correction Demo (Fixed Viewport + Auto Zoom)")
        self.resize(1000, 800)

        self.gl = GLView()

        layout = QVBoxLayout()
        layout.addWidget(self.gl, 1)

        # 控件区
        ctrl = QWidget()
        ctrl_lay = QVBoxLayout(ctrl)

        # 水平透视
        row_h = QHBoxLayout()
        row_h.addWidget(QLabel("水平透视"))
        s_h = QSlider(Qt.Horizontal)
        s_h.setRange(-30, 30)  # 限制在 [-0.9, 0.9]，避免 uScale 无限大
        s_h.setValue(0)
        s_h.valueChanged.connect(
            lambda v: self.gl.set_horizontal_perspective(v / 100.0)
        )
        row_h.addWidget(s_h)
        ctrl_lay.addLayout(row_h)

        # 垂直透视
        row_v = QHBoxLayout()
        row_v.addWidget(QLabel("垂直透视"))
        s_v = QSlider(Qt.Horizontal)
        s_v.setRange(-30, 30)
        s_v.setValue(0)
        s_v.valueChanged.connect(
            lambda v: self.gl.set_vertical_perspective(v / 100.0)
        )
        row_v.addWidget(s_v)
        ctrl_lay.addLayout(row_v)

        layout.addWidget(ctrl, 0)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        # 菜单：打开图片
        action_open = QAction("打开图片(&O)…", self)
        action_open.setShortcut("Ctrl+O")
        action_open.triggered.connect(self.open_image)

        menu = self.menuBar().addMenu("文件(&F)")
        menu.addAction(action_open)

    def open_image(self):
        fn, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if fn:
            self.gl.load_image(fn)


def main():
    app = QApplication(sys.argv)

    fmt = QSurfaceFormat()
        # OpenGL 3.3 Core Profile
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
