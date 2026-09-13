import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:refund_verification_app/features/auth/login_screen.dart';
import 'package:refund_verification_app/state/auth_provider.dart';

void main() {
  group('LoginScreen Tests', () {
    testWidgets('Renders Login fields and validates empty inputs',
        (tester) async {
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider(create: (_) => AuthProvider()),
          ],
          child: const MaterialApp(
            home: LoginScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Merchant Sign In'), findsOneWidget);
      expect(find.text('Sign In to Dashboard'), findsOneWidget);
      expect(find.byType(TextFormField), findsNWidgets(2));

      // Clear email and test validator
      await tester.enterText(find.byType(TextFormField).first, '');
      await tester.tap(find.text('Sign In to Dashboard'));
      await tester.pumpAndSettle();

      expect(find.text('Please enter your email'), findsOneWidget);
    });
  });
}
