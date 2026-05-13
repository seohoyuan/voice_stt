[app]
title = Voice2Spec
package.name = voice2spec
package.domain = org.voice2spec

source.dir = .
source.include_exts = py,txt,md,json,bin
source.include_patterns = bin/*,models/*

version = 0.1.0
requirements = python3,kivy,pyjnius

orientation = portrait
fullscreen = 0

android.permissions = RECORD_AUDIO
android.api = 35
android.minapi = 29
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
