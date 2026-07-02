from get_res import get_res_path
fxg = '\\'
yes_check_img = f"image: url('{get_res_path('icos/yes.png').replace(fxg, '/')}');"
style = """
QLabel.item { 
    min-width: 120px; 
    max-width: 120px; 
}



QSpinBox, QDoubleSpinBox { 
    min-width: 100px; 
}

/* 🎀 樱粉透明主题 by 一只黄小娥  */
QWidget {
    font-family: "Microsoft Yahei";
    font-size: 12pt;
    color: #5E5E5E;
    background: rgba(255, 246, 246, 0.95);
}

/* 面板 */
QScrollArea, QDialog {
    background: rgba(255, 246, 246, 0.95);

}

/* 樱花粉控件 */
QPushButton {
    font: Microsoft Yahei;
    font-weight: bold;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #FFB6C1, stop:1 #FF9AA2);
    border-radius: 5px;
    padding: 6px 10px;
    color: white;
    border: 1px solid #FFA7B2;
}
QPushButton:hover { background: #FF9AA2; }
QPushButton:pressed { background: #FF7F8A; }

/* 透明输入框 */
QSpinBox, QDoubleSpinBox, QComboBox {
    background: rgba(255, 255, 255, 0.3);
    border: 3px solid #FFC0CB;
    border-radius: 4px;
    padding: 2px;
    selection-background-color: #FFB6C1;
}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 2px solid #FF6B7E;
}

/* 樱花滑块 */
QSlider::groove:horizontal {
    height: 6px;
    background: rgba(255, 192, 203, 0.3);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,
        fx:0.5, fy:0.5, stop:0 #FFB6C1, stop:1 #FF9AA2);
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
    border: 1px solid #FFA7B2;
}

/* 渐变色标题 */
QLabel.section_title {
    font-size: 16px;
    font-weight: bold;
    color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #FF6B7E, stop:1 #FF9AA2);

}

/* 果冻感复选框 */

QCheckBox::indicator {
    background: rgba(0,0,0,0);
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #FF9AA2;
}
QCheckBox::indicator:checked {

""" + yes_check_img + """

}
/* 樱花滚动条 */
QScrollBar:vertical {
    background: rgba(255, 238, 238, 0.8);
    width: 10px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 182, 193, 0.6);
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    background: transparent;
}

/* 粉彩数值标签 */
QLabel.fps_label {
    font: Microsoft Yahei;
    font-weight: bold;
    font-size: 14px;
    border-radius: 3px;
    width: 20px;
    margin-right: 3px;
}

/* 柔光按钮选中态 */
QPushButton[flat="false"]:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #FF9AA2, stop:1 #FF7F8A);
    box-shadow: 0 2px 4px rgba(255, 122, 136, 0.3);
}
"""
