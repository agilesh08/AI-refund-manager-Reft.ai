import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:refund_verification_app/core/constants/app_colors.dart';
import 'package:refund_verification_app/shared/widgets/assessment_badge.dart';
import 'package:refund_verification_app/shared/widgets/decision_badge.dart';
import 'package:refund_verification_app/shared/widgets/stat_card.dart';
import 'package:refund_verification_app/shared/widgets/status_badge.dart';

void main() {
  group('Shared Widgets Tests', () {
    testWidgets('AssessmentBadge renders consistent and confidence',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: AssessmentBadge(
              assessmentState: 'EVIDENCE_CONSISTENT',
              confidence: 0.95,
            ),
          ),
        ),
      );

      expect(find.text('Visual AI Assessment'), findsOneWidget);
      expect(find.text('Evidence Consistent'), findsOneWidget);
      expect(find.text('95%'), findsOneWidget);
    });

    testWidgets('AssessmentBadge compact mode', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: AssessmentBadge(
              assessmentState: 'INCONSISTENCY_DETECTED',
              compact: true,
            ),
          ),
        ),
      );

      expect(find.text('Inconsistency Detected'), findsOneWidget);
    });

    testWidgets('DecisionBadge renders approved and distinguishes from AI',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: DecisionBadge(decision: 'REFUND_APPROVED'),
          ),
        ),
      );

      expect(find.text('Merchant Decision'), findsOneWidget);
      expect(find.text('Refund Approved'), findsOneWidget);
    });

    testWidgets('DecisionBadge pending state', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: DecisionBadge(decision: null),
          ),
        ),
      );

      expect(find.text('Awaiting Decision'), findsOneWidget);
    });

    testWidgets('StatusBadge renders formatted state', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: StatusBadge(status: 'IN_PROGRESS'),
          ),
        ),
      );

      expect(find.text('In Progress'), findsOneWidget);
    });

    testWidgets('StatCard displays title, value, and triggers onTap',
        (tester) async {
      bool tapped = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: StatCard(
              title: 'Consistent',
              value: '14',
              icon: Icons.check,
              color: AppColors.assessmentConsistent,
              onTap: () => tapped = true,
            ),
          ),
        ),
      );

      expect(find.text('CONSISTENT'), findsOneWidget);
      expect(find.text('14'), findsOneWidget);

      await tester.tap(find.byType(StatCard));
      expect(tapped, true);
    });
  });
}
