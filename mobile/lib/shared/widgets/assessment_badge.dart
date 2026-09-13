import 'package:flutter/material.dart';
import '../../core/constants/app_colors.dart';

/// Pill badge for Machine Assessment States (EVIDENCE_CONSISTENT, REVIEW_REQUIRED, INCONSISTENCY_DETECTED).
class AssessmentBadge extends StatelessWidget {
  final String? assessmentState;
  final double? confidence;
  final bool compact;

  const AssessmentBadge({
    super.key,
    required this.assessmentState,
    this.confidence,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    if (assessmentState == null || assessmentState!.isEmpty) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3.5),
        decoration: BoxDecoration(
          color: AppColors.surfaceVariant,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppColors.border, width: 0.8),
        ),
        child: const Text(
          'Pending Assessment',
          style: TextStyle(
            fontSize: 10.5,
            fontWeight: FontWeight.w600,
            color: AppColors.textMuted,
          ),
        ),
      );
    }

    final color = AppColors.forAssessment(assessmentState);
    final bgColor = AppColors.forAssessmentBg(assessmentState);

    IconData icon;
    String displayLabel;

    switch (assessmentState!.toUpperCase()) {
      case 'EVIDENCE_CONSISTENT':
        icon = Icons.check_circle_rounded;
        displayLabel = 'Evidence Consistent';
        break;
      case 'REVIEW_REQUIRED':
        icon = Icons.warning_amber_rounded;
        displayLabel = 'Review Required';
        break;
      case 'INCONSISTENCY_DETECTED':
        icon = Icons.error_outline_rounded;
        displayLabel = 'Inconsistency Detected';
        break;
      default:
        icon = Icons.help_outline_rounded;
        displayLabel = assessmentState!
            .split(RegExp(r'[_\s]+'))
            .map((w) => w.isEmpty
                ? ''
                : '${w[0].toUpperCase()}${w.substring(1).toLowerCase()}')
            .join(' ');
    }

    if (compact) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3.5),
        decoration: BoxDecoration(
          color: bgColor,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color.withValues(alpha: 0.35), width: 0.8),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 13, color: color),
            const SizedBox(width: 4.5),
            Text(
              displayLabel,
              style: TextStyle(
                fontSize: 10.5,
                fontWeight: FontWeight.w700,
                color: color,
                letterSpacing: 0.1,
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.4), width: 1.0),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: color),
          const SizedBox(width: 6),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'Visual AI Assessment',
                style: TextStyle(
                  fontSize: 9,
                  letterSpacing: 0.3,
                  fontWeight: FontWeight.w600,
                  color: color.withValues(alpha: 0.85),
                ),
              ),
              Text(
                displayLabel,
                style: TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w800,
                  color: color,
                ),
              ),
            ],
          ),
          if (confidence != null) ...[
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                '${(confidence! * 100).toInt()}%',
                style: TextStyle(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                  color: color,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
