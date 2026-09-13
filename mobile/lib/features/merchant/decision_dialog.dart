import 'package:flutter/material.dart';
import '../../core/constants/app_colors.dart';
import '../../models/merchant_decision_models.dart';

/// Explicit merchant decision confirmation dialog.
class DecisionDialog extends StatefulWidget {
  final String verificationId;
  final Function(MerchantDecisionCreate decision) onConfirm;

  final String? initialDecision;

  const DecisionDialog({
    super.key,
    required this.verificationId,
    required this.onConfirm,
    this.initialDecision,
  });

  @override
  State<DecisionDialog> createState() => _DecisionDialogState();
}

class _DecisionDialogState extends State<DecisionDialog> {
  late String _selectedDecision;
  final TextEditingController _notesController = TextEditingController();
  final Set<String> _selectedRejectionReasons = {};

  @override
  void initState() {
    super.initState();
    _selectedDecision = widget.initialDecision ?? 'REFUND_APPROVED';
  }

  final List<String> _commonRejectionReasons = [
    'Evidence shows no defect or damage',
    'Item does not match product reference specifications',
    'Evidence incomplete or unverified after follow-up',
    'Order delivery and payment signal mismatch',
    'Claim outside merchant return window',
  ];

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  void _submit() {
    final decision = MerchantDecisionCreate(
      decision: _selectedDecision,
      notes: _notesController.text.trim(),
      decisionReason: _notesController.text.trim(),
      rejectionReasons: _selectedDecision == 'REFUND_REJECTED'
          ? _selectedRejectionReasons.toList()
          : null,
      actionTaken: _selectedDecision == 'REFUND_APPROVED'
          ? 'FULL_REFUND'
          : (_selectedDecision == 'REFUND_REJECTED'
              ? 'NO_REFUND'
              : 'ESCALATE_MANUAL_REVIEW'),
    );

    widget.onConfirm(decision);
    Navigator.of(context).pop();
  }

  Widget _buildDecisionChoice({
    required String value,
    required String title,
    required String subtitle,
    required IconData icon,
    required Color color,
    required Color bgColor,
  }) {
    final isSelected = _selectedDecision == value;

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        onTap: () => setState(() => _selectedDecision = value),
        borderRadius: BorderRadius.circular(10),
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: isSelected ? bgColor : Colors.white,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: isSelected ? color : AppColors.border,
              width: isSelected ? 2 : 1,
            ),
          ),
          child: Row(
            children: [
              Icon(
                isSelected
                    ? Icons.radio_button_checked_rounded
                    : Icons.radio_button_off_rounded,
                color: isSelected ? color : AppColors.textMuted,
                size: 20,
              ),
              const SizedBox(width: 10),
              Icon(icon, size: 22, color: color),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: isSelected ? color : AppColors.darkNeutral,
                      ),
                    ),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      titlePadding: const EdgeInsets.fromLTRB(20, 18, 20, 10),
      contentPadding: const EdgeInsets.symmetric(horizontal: 20),
      actionsPadding: const EdgeInsets.fromLTRB(20, 10, 20, 16),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      title: const Row(
        children: [
          Icon(Icons.gavel_rounded, color: AppColors.primary, size: 22),
          SizedBox(width: 10),
          Text(
            'Record Merchant Decision',
            style: TextStyle(
              fontSize: 17,
              fontWeight: FontWeight.w800,
              color: AppColors.darkNeutral,
            ),
          ),
        ],
      ),
      content: SizedBox(
        width: MediaQuery.of(context).size.width * 0.9,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'You are the final authority. Machine consistency evaluations assist but never overrule human judgment.',
                style: TextStyle(
                  fontSize: 12,
                  color: AppColors.textSecondary,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 14),

              // Options
              _buildDecisionChoice(
                value: 'REFUND_APPROVED',
                title: 'Approve Refund',
                subtitle: 'Confirm claim validity and initiate customer refund',
                icon: Icons.check_circle_rounded,
                color: AppColors.decisionApproved,
                bgColor: AppColors.decisionApprovedBg,
              ),
              _buildDecisionChoice(
                value: 'REFUND_REJECTED',
                title: 'Reject Refund',
                subtitle: 'Deny refund due to evidence inconsistencies or policy',
                icon: Icons.cancel_rounded,
                color: AppColors.decisionRejected,
                bgColor: AppColors.decisionRejectedBg,
              ),
              _buildDecisionChoice(
                value: 'MANUAL_REVIEW',
                title: 'Require Manual Review',
                subtitle: 'Escalate to specialist or request internal investigation',
                icon: Icons.rate_review_rounded,
                color: AppColors.decisionManualReview,
                bgColor: AppColors.decisionManualReviewBg,
              ),

              // Rejection reasons checklist if rejecting
              if (_selectedDecision == 'REFUND_REJECTED') ...[
                const SizedBox(height: 6),
                const Text(
                  'Rejection Reasons (Select all that apply)',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 6),
                ..._commonRejectionReasons.map((reason) {
                  final checked = _selectedRejectionReasons.contains(reason);
                  return CheckboxListTile(
                    title: Text(reason, style: const TextStyle(fontSize: 12)),
                    value: checked,
                    activeColor: AppColors.decisionRejected,
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    onChanged: (val) {
                      setState(() {
                        if (val == true) {
                          _selectedRejectionReasons.add(reason);
                        } else {
                          _selectedRejectionReasons.remove(reason);
                        }
                      });
                    },
                  );
                }),
              ],

              const SizedBox(height: 12),
              const Text(
                'Merchant Notes / Rationale',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 6),
              TextField(
                controller: _notesController,
                maxLines: 3,
                decoration: const InputDecoration(
                  hintText: 'Enter notes explaining your determination...',
                  contentPadding: EdgeInsets.all(12),
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.forDecision(_selectedDecision),
            minimumSize: const Size(120, 42),
          ),
          child: const Text('Confirm Decision'),
        ),
      ],
    );
  }
}
