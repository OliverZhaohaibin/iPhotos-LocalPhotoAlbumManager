# -*- coding: utf-8 -*-
"""
PySide6 + OpenGL 3.3 Core Demo
功能：
- 加载一张图片作为纹理
- 在固定“有效框”内显示，并通过滑块绕中心旋转
- CPU 计算“最小必要缩放系数 Scale”，保证任何角度下有效框内无黑边
- 有效框是屏幕中心的静态矩形线框，不随图片旋转/缩放

增强：
- 增加“逆时针 90° 快速旋转”按钮（整体 90° 步进，框 + 图共同变为横/竖构图）
- 增加“水平翻转”按钮（基于当前视角的水平翻转，仅翻图片内容）

依赖：
- PySide6
- PyOpenGL
- numpy

运行：
  python rotate.py
"""

import math
import sys
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtWidgets
from PySide6.QtGui import QSurfaceFormat, QImage
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QFileDialog,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from OpenGL import GL as gl


# --- OpenGL 小工具 -----------------------------------------------------------------


def compile_shader(source: str, shader_type: int) -> int:
    shader = gl.glCreateShader(shader_type)
    src_bytes = source.encode("utf-8")
    gl.glShaderSource(shader, [src_bytes])
    gl.glCompileShader(shader)

    status = gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS)
    if not status:
        log = gl.glGetShaderInfoLog(shader).decode("utf-8", errors="ignore")
        gl.glDeleteShader(shader)
        raise RuntimeError(f"Shader compile error:\n{log}")
    return shader


def link_program(vs_src: str, fs_src: str) -> int:
    vs = compile_shader(vs_src, gl.GL_VERTEX_SHADER)
    fs = compile_shader(fs_src, gl.GL_FRAGMENT_SHADER)
    prog = gl.glCreateProgram()
    gl.glAttachShader(prog, vs)
    gl.glAttachShader(prog, fs)
    gl.glLinkProgram(prog)

    status = gl.glGetProgramiv(prog, gl.GL_LINK_STATUS)
    gl.glDeleteShader(vs)
    gl.glDeleteShader(fs)
    if not status:
        log = gl.glGetProgramInfoLog(prog).decode("utf-8", errors="ignore")
        gl.glDeleteProgram(prog)
        raise RuntimeError(f"Program link error:\n{log}")
    return prog


# --- Shader：图片纹理 --------------------------------------------------------------


VERT_SHADER_SRC = """
#version 330 core

layout (location = 0) in vec2 aPos;       // [-0.5, 0.5] × [-0.5, 0.5]
layout (location = 1) in vec2 aTexCoord;  // [0, 1] × [0, 1]

uniform mat4 uMVP;

out vec2 vTexCoord;

void main()
{
    vTexCoord = aTexCoord;
    gl_Position = uMVP * vec4(aPos, 0.0, 1.0);
}
"""


FRAG_SHADER_SRC = """
#version 330 core

in vec2 vTexCoord;
out vec4 FragColor;

uniform sampler2D uTexture;

void main()
{
    FragColor = texture(uTexture, vTexCoord);
}
"""


# --- Shader：静态线框 Overlay ------------------------------------------------------


OVERLAY_VERT_SHADER_SRC = """
#version 330 core

layout (location = 0) in vec2 aPos;   // 直接为 NDC 坐标

void main()
{
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""


OVERLAY_FRAG_SHADER_SRC = """
#version 330 core

out vec4 FragColor;
uniform vec4 uColor;

void main()
{
    FragColor = uColor;
}
"""


# --- OpenGL 视口 Widget -----------------------------------------------------------


class GLImageWidget(QOpenGLWidget):
    """
    核心渲染组件：
    - 背景黑色
    - 通过 uMVP 矩阵统一实现：Rotate + Optimal Scale + 视口归一化
    - 图像始终“覆盖”中心有效框，无黑边
    - 有效框本身是静态的矩形线框，不随图片旋转
    """

    # 旋转角度限制（度），仅用于滑块微调
    MIN_ANGLE = -45.0
    MAX_ANGLE = 45.0

    def __init__(self, parent=None):
        super().__init__(parent)

        # 主纹理程序
        self.program = None
        self.vao = None
        self.vbo = None
        self.texture = None
        self.u_mvp_loc = -1
        self.u_tex_loc = -1

        # Overlay 线框程序
        self.overlay_program = None
        self.overlay_vao = None
        self.overlay_vbo = None
        self.u_overlay_color = -1

        # 图片信息
        self.image_width = 0
        self.image_height = 0
        self.has_texture = False

        # 旋转角度 & MVP
        # angle_deg：滑块微调角度（-45° ~ +45°，始终相对于“当前基准朝向”）
        self.angle_deg = 0.0  # 当前滑块旋转角度（度）
        self._mvp = np.identity(4, dtype=np.float32)

        # 基准旋转与翻转状态
        # base_rotation_idx: 0,1,2,3 -> 0°, -90°, -180°, -270°
        self.base_rotation_idx = 0
        # is_flipped: 是否进行水平翻转（基于当前视角的水平轴）
        self.is_flipped = False

        # 有效框矩形（Qt 像素坐标系）：(x, y, w, h)
        self.frame_rect = None

        # 背景交给 OpenGL，自身不用填充
        self.setAutoFillBackground(False)

    # ---------- 外部控制接口 ----------

    def set_angle(self, deg: float) -> None:
        """
        设置滑块旋转角度，并限制在 [-45°, +45°] 范围内。
        该角度只是相对于当前“基准旋转”的微调。
        """
        deg = float(deg)
        if deg < self.MIN_ANGLE:
            deg = self.MIN_ANGLE
        if deg > self.MAX_ANGLE:
            deg = self.MAX_ANGLE
        self.angle_deg = deg
        self.update()  # 触发重绘

    def rotate_ccw_90(self) -> None:
        """
        整体逆时针离散旋转 90°（基准旋转）：
        """
        if not self.has_texture:
            return
        # 逆时针应该是 +90°，对应 base_rotation_idx - 1
        self.base_rotation_idx = (self.base_rotation_idx - 1) % 4
        self.frame_rect = None
        self.update()

    def toggle_flip(self) -> None:
        """
        水平翻转：基于当前视角的水平轴翻转图像内容，不影响有效框。
        """
        if not self.has_texture:
            return
        self.is_flipped = not self.is_flipped
        self.update()

    def load_image(self, path: str) -> None:
        """
        加载图片并上传为 OpenGL 纹理。
        """
        img = QImage(path)
        if img.isNull():
            print(f"Failed to load image: {path}")
            return

        # 转为 RGBA 格式
        img = img.convertToFormat(QImage.Format_RGBA8888)

        # 修正 Qt(左上为原点) 和 OpenGL 纹理坐标(Y 轴反向) 的差异
        img = img.mirrored(False, True)

        self.image_width = img.width()
        self.image_height = img.height()

        # PySide6: QImage.bits() 返回 memoryview，直接 tobytes() 即可
        ptr = img.bits()
        raw = ptr.tobytes()

        # OpenGL 纹理上传
        self.makeCurrent()
        if self.texture is None:
            self.texture = gl.glGenTextures(1)

        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)

        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D,
            0,
            gl.GL_RGBA,
            self.image_width,
            self.image_height,
            0,
            gl.GL_RGBA,
            gl.GL_UNSIGNED_BYTE,
            raw,
        )
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self.has_texture = True
        self.doneCurrent()

        # 重置状态
        self.base_rotation_idx = 0
        self.is_flipped = False
        self.angle_deg = 0.0

        # 重置有效框（根据图片和窗口重新计算）
        self.frame_rect = None
        self.update()

    # ---------- OpenGL 生命周期 ----------

    def initializeGL(self) -> None:
        # 纹理 Shader 程序
        self.program = link_program(VERT_SHADER_SRC, FRAG_SHADER_SRC)

        # 顶点数据：一个中心在 (0,0) 的正方形 [-0.5, 0.5]^2
        # 每个顶点: (x, y, u, v)
        quad_vertices = np.array(
            [
                # x,    y,     u, v
                -0.5, -0.5,  0.0, 0.0,
                 0.5, -0.5,  1.0, 0.0,
                -0.5,  0.5,  0.0, 1.0,
                 0.5,  0.5,  1.0, 1.0,
            ],
            dtype=np.float32,
        )

        self.vao = gl.glGenVertexArrays(1)
        self.vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(
            gl.GL_ARRAY_BUFFER,
            quad_vertices.nbytes,
            quad_vertices,
            gl.GL_STATIC_DRAW,
        )

        stride = 4 * 4  # 每顶点 4 个 float
        # 位置属性：location=0, vec2
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(
            0,
            2,
            gl.GL_FLOAT,
            gl.GL_FALSE,
            stride,
            gl.ctypes.c_void_p(0),
        )
        # 纹理坐标属性：location=1, vec2
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(
            1,
            2,
            gl.GL_FLOAT,
            gl.GL_FALSE,
            stride,
            gl.ctypes.c_void_p(2 * 4),
        )

        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)

        # 获取 uniform 位置
        self.u_mvp_loc = gl.glGetUniformLocation(self.program, b"uMVP")
        self.u_tex_loc = gl.glGetUniformLocation(self.program, b"uTexture")

        # Overlay Shader 程序与 VAO/VBO
        self.overlay_program = link_program(
            OVERLAY_VERT_SHADER_SRC,
            OVERLAY_FRAG_SHADER_SRC,
        )

        self.overlay_vao = gl.glGenVertexArrays(1)
        self.overlay_vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.overlay_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.overlay_vbo)
        # 4 个顶点，每个 2 个 float，动态更新
        gl.glBufferData(
            gl.GL_ARRAY_BUFFER,
            4 * 2 * 4,
            None,
            gl.GL_DYNAMIC_DRAW,
        )
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(
            0,
            2,
            gl.GL_FLOAT,
            gl.GL_FALSE,
            0,
            gl.ctypes.c_void_p(0),
        )
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)

        self.u_overlay_color = gl.glGetUniformLocation(
            self.overlay_program, b"uColor"
        )

        # 启用 Alpha 混合（以备 Overlay）
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

    def resizeGL(self, w: int, h: int) -> None:
        gl.glViewport(0, 0, max(1, w), max(1, h))
        # 窗口尺寸变化时，下一帧重新计算有效框
        self.frame_rect = None

    def paintGL(self) -> None:
        # 未加载图片时，用灰色填充
        if not self.has_texture or self.image_width == 0 or self.image_height == 0:
            gl.glClearColor(0.2, 0.2, 0.2, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            return

        # 背景纯黑，方便观察是否有黑边
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        # 1) 根据当前窗口和"基准旋转"重算有效框（宽高比会随 90° / 270° 互换）
        self._recalc_frame_rect()

        # 2) 计算当前“基准旋转 + 滑块微调 + 水平翻转”下的严格无黑边缩放 S，并生成 uMVP
        self._update_mvp_matrix()

        # 3) 绘制图片
        gl.glUseProgram(self.program)

        # 传入矩阵（OpenGL 列主序，这里转置）
        gl.glUniformMatrix4fv(
            self.u_mvp_loc,
            1,
            gl.GL_FALSE,
            self._mvp.T.astype(np.float32),
        )

        # 绑定纹理到纹理单元 0
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glUniform1i(self.u_tex_loc, 0)

        # 绘制矩形（两个三角形条带）
        gl.glBindVertexArray(self.vao)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)

        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        gl.glUseProgram(0)

        # 4) 绘制静态有效框线条（Overlay）
        self._draw_frame_overlay()

    # ---------- 有效框 & MVP 计算 ----------

    def _recalc_frame_rect(self) -> None:
        """
        根据当前窗口大小和图片尺寸，计算中心有效框：
        - 先把整张图按“最长边贴窗”缩放（但要考虑 90°/270° 时宽高对调）
        - 再乘一个 margin_ratio（例如 0.85）留下边距
        - 有效框与图像在“0° 基准方向”时尺寸一致，且居中
        """
        W_win = max(1.0, float(self.width()))
        H_win = max(1.0, float(self.height()))

        if self.image_width <= 0 or self.image_height <= 0:
            # 没图时就给个居中正方形框
            size = min(W_win, H_win) * 0.8
            w_frame = h_frame = size
        else:
            # 原始图片尺寸
            w0 = float(self.image_width)
            h0 = float(self.image_height)

            # 若基准旋转为 90°/270°，逻辑上交换宽高来算“占屏比例”
            if self.base_rotation_idx % 2 == 1:
                w_img = h0
                h_img = w0
            else:
                w_img = w0
                h_img = h0

            # 最大缩放：刚好整图贴满窗口（无边距）
            s_max = min(W_win / w_img, H_win / h_img)
            # 留出一点边距（例如 85%）
            margin_ratio = 0.85
            s_fit = s_max * margin_ratio

            w_frame = w_img * s_fit
            h_frame = h_img * s_fit

        x = (W_win - w_frame) * 0.5
        y = (H_win - h_frame) * 0.5

        self.frame_rect = (x, y, w_frame, h_frame)

    def _update_mvp_matrix(self) -> None:
        """
        使用“严格包含框四个角”的缩放算法生成 uMVP。

        做法：
        1. 将有效框的四个角（在窗口中心坐标系中）逆旋转到图片坐标系中
           （旋转角度 = 基准 90° 步进 + 滑块角度）
        2. 计算使这些点落在图片矩形内部所需的最小统一缩放 S
        3. 若开启水平翻转，则在最终矩阵上对 X 轴乘以 -1（仅翻图像，不动框）
        """
        if self.image_width <= 0 or self.image_height <= 0:
            self._mvp = np.identity(4, dtype=np.float32)
            return

        if self.frame_rect is None:
            self._recalc_frame_rect()

        W_win = max(1.0, float(self.width()))
        H_win = max(1.0, float(self.height()))
        _, _, W_frame, H_frame = self.frame_rect

        w_img = float(self.image_width)
        h_img = float(self.image_height)

        # 总角度 = 基准 90° 步进 + 滑块微调
        total_deg = (self.base_rotation_idx * -90.0) + self.angle_deg
        theta = math.radians(total_deg)
        c = math.cos(theta)
        s = math.sin(theta)

        # ---- 关键：基于“逆旋转框角”的严格缩放 ----
        half_Wf = W_frame * 0.5
        half_Hf = H_frame * 0.5

        # 框在“窗口中心坐标系”中的四个角（以 0 为中心）
        corners = [
            (-half_Wf, -half_Hf),
            ( half_Wf, -half_Hf),
            ( half_Wf,  half_Hf),
            (-half_Wf,  half_Hf),
        ]

        S_min = 0.0
        for xf, yf in corners:
            # 把框角逆向旋转到“图像坐标系”中
            # R(-θ) = [[c, s], [-s, c]]
            x_prime =  xf * c + yf * s
            y_prime = -xf * s + yf * c

            # 让这些点都落在 [-w_img/2, w_img/2] × [-h_img/2, h_img/2] 内
            S_corner = max(
                2.0 * abs(x_prime) / w_img,
                2.0 * abs(y_prime) / h_img,
            )
            if S_corner > S_min:
                S_min = S_corner

        if S_min < 1e-6:
            S_min = 1e-6

        S = S_min

        # 归一化到“整个窗口”的 NDC，同之前推导
        m00 = 2.0 * S * w_img * c / W_win
        m01 = 2.0 * S * (-h_img * s) / W_win
        m10 = 2.0 * S * w_img * s / H_win
        m11 = 2.0 * S * h_img * c / H_win

        # 若开启水平翻转：在最终视图空间对 X 轴乘以 -1
        # 等价于在矩阵左上角（影响 x_ndc）取反
        if self.is_flipped:
            m00 = -m00
            m01 = -m01

        self._mvp = np.array(
            [
                [m00, m01, 0.0, 0.0],
                [m10, m11, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )

    # ---------- Overlay 线框绘制 ----------

    def _update_frame_geometry(self) -> None:
        """
        把 frame_rect 转成 4 个 NDC 顶点，更新到 overlay_vbo。
        """
        if self.overlay_vbo is None or self.frame_rect is None:
            return

        W_win = max(1.0, float(self.width()))
        H_win = max(1.0, float(self.height()))
        x, y, w_frame, h_frame = self.frame_rect

        # Qt 像素坐标 -> NDC
        left = x
        right = x + w_frame
        top = y
        bottom = y + h_frame

        # 转 NDC：x_ndc = 2*(x/W - 0.5), y_ndc = 2*(0.5 - y/H)
        x_l = 2.0 * (left / W_win - 0.5)
        x_r = 2.0 * (right / W_win - 0.5)
        y_t = 2.0 * (0.5 - top / H_win)
        y_b = 2.0 * (0.5 - bottom / H_win)

        # 顶点顺序：左上, 右上, 右下, 左下（LINE_LOOP）
        verts = np.array(
            [
                x_l, y_t,
                x_r, y_t,
                x_r, y_b,
                x_l, y_b,
            ],
            dtype=np.float32,
        )

        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.overlay_vbo)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, verts.nbytes, verts)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

    def _draw_frame_overlay(self) -> None:
        """
        使用单独的 Overlay Shader 在 NDC 空间绘制静态矩形线框。
        """
        if self.overlay_program is None or self.overlay_vao is None:
            return
        if self.frame_rect is None:
            return

        self._update_frame_geometry()

        gl.glUseProgram(self.overlay_program)
        gl.glBindVertexArray(self.overlay_vao)

        # 线框颜色：白色，完全不透明
        gl.glUniform4f(self.u_overlay_color, 1.0, 1.0, 1.0, 1.0)

        # 为避免某些驱动 GL_INVALID_VALUE，这里使用 1.0
        gl.glLineWidth(1.0)
        gl.glDrawArrays(gl.GL_LINE_LOOP, 0, 4)

        gl.glBindVertexArray(0)
        gl.glUseProgram(0)


# --- 主窗口与 UI -------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("OpenGL Rotation + Optimal Cover Demo (±45° + 90°&Flip)")
        self.resize(960, 600)

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 渲染视口（固定有效框）
        self.gl_widget = GLImageWidget(self)
        layout.addWidget(self.gl_widget, stretch=1)

        # 控制面板（加载按钮 + 快速旋转 + 翻转 + 角度滑块）
        control_bar = QHBoxLayout()
        control_bar.setContentsMargins(0, 0, 0, 0)
        control_bar.setSpacing(8)

        # 加载图片
        self.load_btn = QPushButton("加载图片")
        self.load_btn.clicked.connect(self.on_load_image)
        control_bar.addWidget(self.load_btn)

        # 新增：逆时针 90° 快速旋转按钮
        self.rotate_ccw_btn = QPushButton("逆时针90°")
        self.rotate_ccw_btn.clicked.connect(self.on_rotate_ccw)
        control_bar.addWidget(self.rotate_ccw_btn)

        # 新增：水平翻转按钮
        self.flip_h_btn = QPushButton("水平翻转")
        self.flip_h_btn.clicked.connect(self.on_flip_horizontal)
        control_bar.addWidget(self.flip_h_btn)

        # 角度标签（显示滑块微调角度）
        self.angle_label = QLabel("角度: 0°")
        control_bar.addWidget(self.angle_label)

        # 滑块：仅控制 ±45° 微调
        self.slider = QSlider(QtCore.Qt.Horizontal)
        # 角度范围限制在 ±45°
        self.slider.setRange(int(GLImageWidget.MIN_ANGLE), int(GLImageWidget.MAX_ANGLE))
        self.slider.setSingleStep(1)
        self.slider.setValue(0)
        self.slider.valueChanged.connect(self.on_angle_changed)
        control_bar.addWidget(self.slider, stretch=1)

        layout.addLayout(control_bar)

    # ---------- 槽函数 ----------

    def on_load_image(self):
        dlg = QFileDialog(self, "选择图片")
        dlg.setFileMode(QFileDialog.ExistingFile)
        dlg.setNameFilter("Images (*.png *.jpg *.jpeg *.bmp *.gif)")
        if dlg.exec() == QFileDialog.Accepted:
            path = dlg.selectedFiles()[0]
            self.gl_widget.load_image(path)
            # 重置 UI 显示
            self.slider.blockSignals(True)
            self.slider.setValue(0)
            self.slider.blockSignals(False)
            self.angle_label.setText("角度: 0°")

    def on_angle_changed(self, value: int):
        self.angle_label.setText(f"角度: {value}°")
        self.gl_widget.set_angle(float(value))

    def on_rotate_ccw(self):
        self.gl_widget.rotate_ccw_90()

    def on_flip_horizontal(self):
        self.gl_widget.toggle_flip()


# --- 入口 -------------------------------------------------------------------------


def main():
    # 全局设置 OpenGL 3.3 Core Profile
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.OpenGL)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
