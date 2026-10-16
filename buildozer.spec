[app]
title = SalesRep AI Zambia
package.name = salesrepai
package.domain = zm.salesrep
source.dir = .
source.include_exts = py,png,jpg,json
source.exclude_dirs = .github, bin
version = 2.3
requirements = python3,kivy==2.3.0,plyer,pyjnius
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,POST_NOTIFICATIONS,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,VIBRATE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
