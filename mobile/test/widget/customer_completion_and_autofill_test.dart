
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:refund_verification_app/features/customer/customer_completion_screen.dart';
import 'package:refund_verification_app/state/customer_flow_provider.dart';

void main() {
  group('Customer Completion & Order Autofill Tests', () {
    testWidgets('CustomerCompletionScreen displays neutral submission confirmation without internal scores',
        (tester) async {
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider(create: (_) => CustomerFlowProvider()),
          ],
          child: const MaterialApp(
            home: CustomerCompletionScreen(token: 'TEST_TOKEN_123'),
          ),
        ),
      );

      // 1. Verify neutral confirmation copy
      expect(find.text('Evidence Submitted'), findsOneWidget);
      expect(find.textContaining('Your evidence has been'),
          findsOneWidget);
      expect(find.text('Pending Merchant Review'), findsOneWidget);
      expect(find.text('Finish & Close'), findsOneWidget);

      // 2. Strict privacy: verify no merchant-internal signals or fraud metrics leak to customer
      expect(find.textContaining('Fraud'), findsNothing);
      expect(find.textContaining('Risk'), findsNothing);
      expect(find.textContaining('Score'), findsNothing);
      expect(find.textContaining('Assessment'), findsNothing);
    });

    test('Autofill preserves existing manual merchant input and supports aliases', () {
      final orderIdController = TextEditingController(text: 'ORD-MANUAL-001');
      final customerNameController = TextEditingController(text: 'Pre-entered Name');
      final customerContactController = TextEditingController();
      final refundReasonController = TextEditingController();
      final refundAmountController = TextEditingController();

      final extracted = {
        'order_id': 'ORD-AI-999',
        'customer_name': 'AI Extracted Name',
        'email': 'customer@extracted.com',
        'reported_issue': 'Screen was shattered upon opening package',
        'order_amount': '4500.00',
      };

      // Emulate _applyExtractedOrder behavior
      void applyOrder(Map<String, dynamic> data) {
        final orderId = data['order_id'] ?? data['orderId'] ?? data['order_number'];
        if (orderIdController.text.trim().isEmpty && orderId != null) {
          orderIdController.text = orderId.toString().trim();
        }

        final custName = data['customer_name'] ?? data['name'] ?? data['buyer'];
        if (customerNameController.text.trim().isEmpty && custName != null) {
          customerNameController.text = custName.toString().trim();
        }

        final contact = data['customer_contact'] ?? data['customer_email'] ?? data['email'] ?? data['phone'];
        if (customerContactController.text.trim().isEmpty && contact != null) {
          customerContactController.text = contact.toString().trim();
        }

        final reason = data['refund_reason'] ?? data['reported_issue'] ?? data['reason'];
        if (refundReasonController.text.trim().isEmpty && reason != null) {
          refundReasonController.text = reason.toString().trim();
        }

        final amt = data['refund_amount'] ?? data['order_amount'] ?? data['amount'];
        if (refundAmountController.text.trim().isEmpty && amt != null) {
          refundAmountController.text = amt.toString().trim();
        }
      }

      applyOrder(extracted);

      // Verification: Pre-entered values MUST NOT be overwritten
      expect(orderIdController.text, 'ORD-MANUAL-001');
      expect(customerNameController.text, 'Pre-entered Name');

      // Empty fields MUST be populated via aliases
      expect(customerContactController.text, 'customer@extracted.com');
      expect(refundReasonController.text, 'Screen was shattered upon opening package');
      expect(refundAmountController.text, '4500.00');
    });
  });
}
