import 'package:flutter/material.dart';
import '../../core/constants/app_colors.dart';

/// Pill badge for Human Merchant Decisions (REFUND_APPROVED, REFUND_REJECTED, MANUAL_REVIEW).
/// Strictly distinguished from AI Assessment Badges.
class DecisionBadge extends StatelessWidget {
  final String? decision;
  final bool compact;

  const DecisionBadge({
    super.key,
    required this.decision,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    final norm = (decision ?? '').toUpperCase().trim();
    if (norm.isEmpty || norm == 'AWAITING_DECISION' || norm == 'AWAITING DECISION' || norm == 'NONE') {
      if (compact) {
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3.5),
          decoration: BoxDecoration(
            color: AppColors.surfaceVariant,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: AppColors.border, width: 0.8),
          ),
          child: const Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.hourglass_empty_rounded, size: 12, color: AppColors.textSecondary),
              SizedBox(width: 4),
              Text(
                'AWAITING DECISION',
                style: TextStyle(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textSecondary,
                  letterSpacing: 0.2,
                ),
              ),
            ],
          ),
        );
      }

      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3.5),
        decoration: BoxDecoration(
          color: AppColors.surfaceVariant,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: AppColors.border, width: 0.8),
        ),
        child: const Text(
          'Awaiting Decision',
          style: TextStyle(
            fontSize: 10.5,
            fontWeight: FontWeight.w600,
            color: AppColors.textSecondary,
          ),
        ),
      );
    }

    final color = AppColors.forDecision(decision);
    final bgColor = AppColors.forDecisionBg(decision);

    IconData icon;
    String displayLabel;

    switch (norm) {
      case 'HOLD':
      case 'HELD':
        icon = Icons.pause_circle_filled_rounded;
        displayLabel = compact ? 'HOLD' : 'Hold';
        break;
      case 'REFUND_APPROVED':
      case 'APPROVED':
        icon = Icons.check_circle_rounded;
        displayLabel = compact ? 'APPROVED' : 'Refund Approved';
        break;
      case 'REFUND_REJECTED':
      case 'REJECTED':
        icon = Icons.cancel_rounded;
        displayLabel = compact ? 'REJECTED' : 'Refund Rejected';
        break;
      case 'MANUAL_REVIEW':
        icon = Icons.rate_review_rounded;
        displayLabel = compact ? 'MANUAL REVIEW' : 'Manual Review';
        break;
      default:
        icon = Icons.gavel_rounded;
        displayLabel = decision!.split(RegExp(r'[_\s]+')).map((w) => w.isEmpty ? '' : '${w[0].toUpperCase()}${w.substring(1).toLowerCase()}').join(' ');
    }

    if (compact) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3.5),
        decoration: BoxDecoration(
          color: bgColor,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color.withValues(alpha: 0.4), width: 0.8),
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
        border: Border.all(color: color.withValues(alpha: 0.5), width: 1.0),
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
                'Merchant Decision',
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
        ],
      ),
    );
  }
}
