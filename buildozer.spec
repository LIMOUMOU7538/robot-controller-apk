[app]
# 应用显示名称
title = RobotController

# 包名，改成你自己的域名反写
package.name = robotcontroller
package.domain = org.example

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,json,atlas

version = 1.0

# websockets 是纯 Python 包，p4a 会直接 pip 安装
requirements = python3,kivy==2.3.0,websockets

# 手机横屏复刻桌面布局
orientation = landscape
fullscreen = 1

android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 33
android.minapi = 24
android.archs = arm64-v8a

# 摄像头走明文 ws:// / udp://，安卓 9+ 必须允许明文流量
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
