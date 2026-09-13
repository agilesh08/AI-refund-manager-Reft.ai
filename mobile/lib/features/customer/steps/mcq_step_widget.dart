import 'package:flutter/material.dart';
import '../../../core/constants/app_colors.dart';
import '../../../models/workflow_step.dart';

/// Multiple choice dynamic workflow step widget.
class McqStepWidget extends StatelessWidget {
  final WorkflowStepItem step;
  final String? selectedValue;
  final ValueChanged<String> onSelected;

  const McqStepWidget({
    super.key,
    required this.step,
    required this.selectedValue,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    final options = step.options.isNotEmpty
        ? step.options
        : [
            WorkflowOption(value: 'Yes', label: 'Yes'),
            WorkflowOption(value: 'No', label: 'No'),
            WorkflowOption(value: 'Partially', label: 'Partially'),
          ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (step.description != null && step.description!.isNotEmpty) ...[
          Text(
            step.description!,
            style: const TextStyle(
              fontSize: 14,
              color: AppColors.textSecondary,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 16),
        ],
        ...options.map((opt) {
          final isSelected =
              selectedValue == opt.value || selectedValue == opt.label;
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: InkWell(
              onTap: () => onSelected(opt.value),
              borderRadius: BorderRadius.circular(10),
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                decoration: BoxDecoration(
                  color: isSelected
                      ? AppColors.primaryLight.withValues(alpha: 0.35)
                      : Colors.white,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: isSelected ? AppColors.primary : AppColors.border,
                    width: isSelected ? 1.8 : 1,
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      isSelected
                          ? Icons.radio_button_checked_rounded
                          : Icons.radio_button_off_rounded,
                      color:
                          isSelected ? AppColors.primary : AppColors.textMuted,
                      size: 20,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            opt.label,
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight:
                                  isSelected ? FontWeight.w700 : FontWeight.w500,
                              color: isSelected
                                  ? AppColors.darkNeutral
                                  : AppColors.darkNeutral.withValues(alpha: 0.85),
                            ),
                          ),
                          if (opt.description != null &&
                              opt.description!.isNotEmpty) ...[
                            const SizedBox(height: 4),
                            Text(
                              opt.description!,
                              style: const TextStyle(
                                fontSize: 12,
                                color: AppColors.textSecondary,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }),
      ],
    );
  }
}
