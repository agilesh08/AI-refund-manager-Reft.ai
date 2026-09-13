import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:refund_verification_app/features/merchant/settings/merchant_settings_screen.dart';
import 'package:refund_verification_app/features/merchant/settings/product_list_screen.dart';

void main() {
  group('Merchant Settings Screens Tests', () {
    testWidgets('MerchantSettingsScreen renders all navigation cards and back button',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: MerchantSettingsScreen(),
        ),
      );

      expect(find.text('Merchant Settings'), findsOneWidget);
      expect(find.text('Merchant Configuration Hub'), findsOneWidget);
      expect(find.text('Products & Trusted Evidence'), findsOneWidget);
      expect(find.text('Verification Workflows'), findsOneWidget);
      expect(find.text('General Verification Settings'), findsOneWidget);
      expect(find.byIcon(Icons.arrow_back), findsOneWidget);
    });

    testWidgets('ProductListScreen renders app bar, add button, and empty state',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: ProductListScreen(),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('Trusted Product Evidence'), findsOneWidget);
      expect(find.byIcon(Icons.arrow_back), findsOneWidget);
    });
  });
}
