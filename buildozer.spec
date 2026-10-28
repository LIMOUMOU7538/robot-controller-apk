[app]
# 应用显示名称
title = RobotController

# 包名，改成你自己的域名反写
package.name = robotcontroller
package.domain = org.example

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,json,atlas

version = 1.0

# websockets锁定稳定版本，规避p4a编译异常
requirements = python3,kivy==2.3.0,websockets==12.0

# 手机横屏复刻桌面布局
orientation = landscape
fullscreen = 1

android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 33
android.minapi = 24
android.archs = arm64-v8a

# 安卓9+ 允许明文ws://、UDP通信，关键配置，不加无法局域网连接小车
android.uses_cleartext_traffic = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
