# Shared Android build paths. Explicit make variables take precedence, followed
# by the standard Android environment variables and per-user SDK location.
HOST_OS := $(shell uname -s)
NDK_HOST_TAG ?= $(if $(filter Darwin,$(HOST_OS)),darwin-x86_64,linux-x86_64)
SDK_PLATFORM_DEFAULT := $(HOME)/$(if $(filter Darwin,$(HOST_OS)),Library/Android/sdk,Android/Sdk)
SDK_DEFAULT := $(shell for candidate in "$(SDK_PLATFORM_DEFAULT)" \
  "$(HOME)/Android/Sdk" "$(HOME)/Android/sdk" "$(HOME)/android-sdk"; do \
  if test -d "$$candidate"; then printf '%s' "$$candidate"; break; fi; done)
SDK ?= $(if $(ANDROID_SDK_ROOT),$(ANDROID_SDK_ROOT),$(if $(ANDROID_HOME),$(ANDROID_HOME),$(if $(SDK_DEFAULT),$(SDK_DEFAULT),$(SDK_PLATFORM_DEFAULT))))
NDK ?= $(if $(ANDROID_NDK_HOME),$(ANDROID_NDK_HOME),$(if $(ANDROID_NDK_ROOT),$(ANDROID_NDK_ROOT),$(SDK)/ndk/28.2.13676358))
TOOLCHAIN ?= $(NDK)/toolchains/llvm/prebuilt/$(NDK_HOST_TAG)
BUILD_TOOLS ?= $(SDK)/build-tools/37.0.0
ANDROID_JAR ?= $(SDK)/platforms/android-36/android.jar
D8 ?= $(BUILD_TOOLS)/d8
KEYSTORE ?= $(HOME)/.android/debug.keystore

# Use the same JDK for direct make builds and Python-driven builds.
ifneq ($(JAVA_HOME),)
export PATH := $(JAVA_HOME)/bin:$(PATH)
endif
