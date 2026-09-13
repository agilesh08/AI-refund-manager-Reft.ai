import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:refund_verification_app/features/gateway/gateway_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('GatewayScreen Tests', () {
    testWidgets('Renders consumer-facing Customer Verification screen with Reft.AI branding',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: GatewayScreen(),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.bySemanticsLabel('Reft.AI'), findsNWidgets(2));
      expect(find.text('Customer Verification'), findsOneWidget);
      expect(find.text('Continue'), findsOneWidget);
      expect(find.byType(TextField), findsOneWidget);
      expect(find.byTooltip('Merchant Login'), findsOneWidget);
    });
  });
}
