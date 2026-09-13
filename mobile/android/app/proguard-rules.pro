# Flutter-specific ProGuard rules
# Keep Flutter engine
-keep class io.flutter.** { *; }
-keep class io.flutter.plugins.** { *; }
-keep class io.flutter.plugin.** { *; }
-keep class io.flutter.util.** { *; }
-keep class io.flutter.view.** { *; }
-keep class io.flutter.embedding.** { *; }

# Keep annotations
-keepattributes *Annotation*
-keepattributes Signature

# Suppress warnings for missing references
-dontwarn io.flutter.embedding.**

# flutter_secure_storage
-keep class com.it_nomads.fluttersecurestorage.** { *; }
