import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:refund_verification_app/features/merchant/dashboard_screen.dart';
import 'package:refund_verification_app/features/merchant/decision_dialog.dart';
import 'package:refund_verification_app/models/merchant_decision_models.dart';
import 'package:refund_verification_app/state/auth_provider.dart';
import 'package:refund_verification_app/state/merchant_dashboard_provider.dart';

void main() {
  group('Merchant Screens Widget Tests', () {
    testWidgets('DashboardScreen renders stats cards, search, and filters',
        (tester) async {
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider(create: (_) => AuthProvider()),
            ChangeNotifierProvider(create: (_) => MerchantDashboardProvider()),
          ],
          child: const MaterialApp(
            home: DashboardScreen(),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.bySemanticsLabel('Reft.AI'), findsOneWidget);
      expect(find.text('TOTAL'), findsOneWidget);
      expect(find.text('REVIEW REQUIRED'), findsOneWidget);
      expect(find.text('CONSISTENT'), findsNothing);
      expect(find.text('INCONSISTENT'), findsNothing);
      expect(find.text('Create New Verification'), findsOneWidget);
      expect(find.text('Filter'), findsOneWidget);
    });

    testWidgets('DecisionDialog renders options and confirms decision',
        (tester) async {
      MerchantDecisionCreate? recorded;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: DecisionDialog(
              verificationId: 'sess_001',
              onConfirm: (dec) => recorded = dec,
            ),
          ),
        ),
      );

      expect(find.text('Record Merchant Decision'), findsOneWidget);
      expect(find.text('Approve Refund'), findsOneWidget);
      expect(find.text('Reject Refund'), findsOneWidget);
      expect(find.text('Require Manual Review'), findsOneWidget);
      expect(find.text('Confirm Decision'), findsOneWidget);

      // Select Reject Refund
      await tester.tap(find.text('Reject Refund'));
      await tester.pumpAndSettle();

      // Confirm rejection reasons appear
      expect(find.text('Rejection Reasons (Select all that apply)'), findsOneWidget);
      expect(find.text('Evidence shows no defect or damage'), findsOneWidget);

      // Select a rejection reason
      await tester.tap(find.text('Evidence shows no defect or damage'));
      await tester.pumpAndSettle();

      // Enter notes
      await tester.enterText(
          find.byType(TextField), 'Damage pattern does not match package condition.');

      // Tap Confirm Decision
      await tester.tap(find.text('Confirm Decision'));
      await tester.pumpAndSettle();

      expect(recorded, isNotNull);
      expect(recorded!.decision, 'REFUND_REJECTED');
      expect(recorded!.rejectionReasons, contains('Evidence shows no defect or damage'));
      expect(recorded!.notes, 'Damage pattern does not match package condition.');
    });
  });
}
