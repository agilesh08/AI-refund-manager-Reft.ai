import 'package:flutter/material.dart';
import '../../../core/constants/app_colors.dart';
import '../../../models/workflow_step.dart';

/// Order details confirmation dynamic workflow step widget.
class OrderStepWidget extends StatefulWidget {
  final WorkflowStepItem step;
  final String? initialValue;
  final ValueChanged<String> onChanged;

  const OrderStepWidget({
    super.key,
    required this.step,
    this.initialValue,
    required this.onChanged,
  });

  @override
  State<OrderStepWidget> createState() => _OrderStepWidgetState();
}

class _OrderStepWidgetState extends State<OrderStepWidget> {
  bool _boxReceived = true;
  bool _allAccessoriesIncluded = true;
  bool _factorySealIntact = false;
  final TextEditingController _notesController = TextEditingController();

  void _notify() {
    final summary =
        'Box Received: $_boxReceived, Accessories: $_allAccessoriesIncluded, Seal Intact: $_factorySealIntact. Notes: ${_notesController.text.trim()}';
    widget.onChanged(summary);
  }

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (widget.step.description != null &&
            widget.step.description!.isNotEmpty) ...[
          Text(
            widget.step.description!,
            style: const TextStyle(
              fontSize: 14,
              color: AppColors.textSecondary,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 16),
        ],
        SwitchListTile(
          title: const Text('Original Retail Box Received',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
          value: _boxReceived,
          activeThumbColor: AppColors.primary,
          contentPadding: EdgeInsets.zero,
          onChanged: (val) {
            setState(() => _boxReceived = val);
            _notify();
          },
        ),
        SwitchListTile(
          title: const Text('All Manuals & Accessories Present',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
          value: _allAccessoriesIncluded,
          activeThumbColor: AppColors.primary,
          contentPadding: EdgeInsets.zero,
          onChanged: (val) {
            setState(() => _allAccessoriesIncluded = val);
            _notify();
          },
        ),
        SwitchListTile(
          title: const Text('Manufacturer Seal Was Intact On Arrival',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
          value: _factorySealIntact,
          activeThumbColor: AppColors.primary,
          contentPadding: EdgeInsets.zero,
          onChanged: (val) {
            setState(() => _factorySealIntact = val);
            _notify();
          },
        ),
        const SizedBox(height: 12),
        const Text(
          'Additional Item Condition Notes',
          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 6),
        TextField(
          controller: _notesController,
          maxLines: 2,
          decoration: const InputDecoration(
            hintText: 'Any extra order context...',
          ),
          onChanged: (_) => _notify(),
        ),
      ],
    );
  }
}
