import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:refund_verification_app/features/customer/customer_completion_screen.dart';
import 'package:refund_verification_app/features/customer/invalid_token_screen.dart';
import 'package:refund_verification_app/features/customer/steps/delivery_step_widget.dart';
import 'package:refund_verification_app/features/customer/steps/image_step_widget.dart';
import 'package:refund_verification_app/features/customer/steps/mcq_step_widget.dart';
import 'package:refund_verification_app/features/customer/steps/order_step_widget.dart';
import 'package:refund_verification_app/features/customer/steps/text_step_widget.dart';
import 'package:refund_verification_app/models/workflow_step.dart';
import 'package:refund_verification_app/state/customer_flow_provider.dart';

void main() {
  group('Customer Flow & Step Widgets Tests', () {
    testWidgets('McqStepWidget renders choices and calls onSelected',
        (tester) async {
      String? selected;
      final step = WorkflowStepItem(
        stepKey: 'step_mcq',
        stepType: 'MCQ',
        title: 'Packaging condition',
        config: {
          'choices': ['Intact', 'Damaged', 'Missing'],
        },
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: McqStepWidget(
              step: step,
              selectedValue: selected,
              onSelected: (val) => selected = val,
            ),
          ),
        ),
      );

      expect(find.text('Intact'), findsOneWidget);
      expect(find.text('Damaged'), findsOneWidget);
      expect(find.text('Missing'), findsOneWidget);

      await tester.tap(find.text('Damaged'));
      expect(selected, 'Damaged');
    });

    testWidgets('TextStepWidget accepts text input', (tester) async {
      String? textValue;
      final step = WorkflowStepItem(
        stepKey: 'step_text',
        stepType: 'TEXT',
        title: 'Issue Description',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TextStepWidget(
              step: step,
              onChanged: (val) => textValue = val,
            ),
          ),
        ),
      );

      await tester.enterText(
          find.byType(TextField), 'The item stopped working after 2 hours.');
      expect(textValue, 'The item stopped working after 2 hours.');
    });

    testWidgets('OrderStepWidget toggles checklist switches', (tester) async {
      String? summary;
      final step = WorkflowStepItem(
        stepKey: 'step_order',
        stepType: 'ORDER',
        title: 'Order verification',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: OrderStepWidget(
              step: step,
              onChanged: (val) => summary = val,
            ),
          ),
        ),
      );

      expect(find.text('Original Retail Box Received'), findsOneWidget);
      expect(find.text('All Manuals & Accessories Present'), findsOneWidget);
      expect(
          find.text('Manufacturer Seal Was Intact On Arrival'), findsOneWidget);

      // Toggle switch
      await tester.tap(find.byType(Switch).first);
      expect(summary, contains('Box Received: false'));
    });

    testWidgets('DeliveryStepWidget renders condition and carrier inputs',
        (tester) async {
      String? deliveryData;
      final step = WorkflowStepItem(
        stepKey: 'step_delivery',
        stepType: 'DELIVERY',
        title: 'Delivery confirmation',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: DeliveryStepWidget(
              step: step,
              onChanged: (val) => deliveryData = val,
            ),
          ),
        ),
      );

      expect(find.text('Outer Parcel Condition Upon Arrival'), findsOneWidget);
      expect(find.text('Delivery Carrier (Optional)'), findsOneWidget);

      await tester.enterText(find.byType(TextField).first, 'FedEx Express');
      expect(deliveryData, contains('Carrier: FedEx Express'));
    });

    testWidgets('InvalidTokenScreen renders polite message and home button',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: InvalidTokenScreen(),
        ),
      );

      expect(find.text('Verification Link Expired or Invalid'), findsOneWidget);
      expect(find.text('Return to Home'), findsOneWidget);
    });

    testWidgets('CustomerCompletionScreen renders confirmation without internal flags',
        (tester) async {
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider(create: (_) => CustomerFlowProvider()),
          ],
          child: const MaterialApp(
            home: CustomerCompletionScreen(token: 'test_token'),
          ),
        ),
      );

      expect(find.text('Evidence Submitted'), findsOneWidget);
      expect(find.textContaining('Your evidence has been'), findsOneWidget);
      expect(find.text('Pending Merchant Review'), findsOneWidget);
      expect(find.text('Finish & Close'), findsOneWidget);
    });

    testWidgets(
        'McqStepWidget renders clean label from Map options and not raw map string',
        (tester) async {
      String? selected;
      final step = WorkflowStepItem(
        stepKey: 'step_scenario',
        stepType: 'MCQ',
        title: 'Select Refund Reason',
        config: {
          'options': [
            {
              'value': 'damaged',
              'label': 'Product arrived damaged',
              'description': 'Item has visible scratches or cracks',
            },
            {
              'value': 'defective',
              'label': 'Defective or not working',
            },
          ],
        },
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: McqStepWidget(
              step: step,
              selectedValue: selected,
              onSelected: (val) => selected = val,
            ),
          ),
        ),
      );

      // Clean label must be rendered
      expect(find.text('Product arrived damaged'), findsOneWidget);
      expect(find.text('Defective or not working'), findsOneWidget);
      expect(
          find.text('Item has visible scratches or cracks'), findsOneWidget);

      // Raw map representation must NOT be rendered
      expect(find.textContaining('{value:'), findsNothing);
      expect(find.textContaining('{label:'), findsNothing);

      await tester.tap(find.text('Product arrived damaged'));
      expect(selected, 'damaged');
    });

    testWidgets(
        'ImageStepWidget displays 4 camera tips and disables gallery in camera-only mode',
        (tester) async {
      final step = WorkflowStepItem(
        stepKey: 'step_initial_proof',
        stepType: 'CAMERA',
        title: 'Show Us the Issue',
        config: {
          'camera_only': true,
          'allow_gallery': false,
        },
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: ImageStepWidget(
                step: step,
                onImagePicked: (file, filename) {},
              ),
            ),
          ),
        ),
      );

      // Verify instructions and 4 tips are visible
      expect(find.text('Photo Verification Instructions'), findsOneWidget);
      expect(find.text('1. Keep entire product visible in the frame'),
          findsOneWidget);
      expect(find.text('2. Ensure good lighting and avoid glare'),
          findsOneWidget);
      expect(find.text('3. Focus on the specific damage or issue'),
          findsOneWidget);
      expect(find.text('4. Keep the device steady while taking the photo'),
          findsOneWidget);

      // Verify Camera-only button exists
      expect(find.text('Open Camera & Capture Proof'), findsOneWidget);

      // Verify Gallery button is completely hidden / absent
      expect(find.text('Gallery'), findsNothing);
    });
  });
}

