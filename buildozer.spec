[app]
title = Voice2Spec
package.name = voice2spec
package.domain = org.voice2spec

source.dir = .
source.include_exts = py,txt,md,json,bin,otf,ttf,ttc
source.include_patterns = assets/fonts/*,bin/*,models/*

version = 0.1.0
requirements = python3,kivy,pyjnius

orientation = portrait
fullscreen = 0

android.permissions = RECORD_AUDIO,INTERNET
android.api = 35
android.minapi = 29
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
