import 'package:flutter/material.dart';
import '../../../core/constants/app_colors.dart';
import '../../../models/workflow_step.dart';

/// Delivery carrier & package condition dynamic workflow step widget.
class DeliveryStepWidget extends StatefulWidget {
  final WorkflowStepItem step;
  final String? initialValue;
  final ValueChanged<String> onChanged;

  const DeliveryStepWidget({
    super.key,
    required this.step,
    this.initialValue,
    required this.onChanged,
  });

  @override
  State<DeliveryStepWidget> createState() => _DeliveryStepWidgetState();
}

class _DeliveryStepWidgetState extends State<DeliveryStepWidget> {
  String _packageCondition = 'INTACT';
  final TextEditingController _carrierController = TextEditingController();
  final TextEditingController _trackingController = TextEditingController();

  void _notify() {
    final summary =
        'Carrier: ${_carrierController.text.trim()}; Tracking: ${_trackingController.text.trim()}; Condition: $_packageCondition';
    widget.onChanged(summary);
  }

  @override
  void dispose() {
    _carrierController.dispose();
    _trackingController.dispose();
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
        const Text(
          'Outer Parcel Condition Upon Arrival',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: AppColors.darkNeutral,
          ),
        ),
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(
          initialValue: _packageCondition,
          items: const [
            DropdownMenuItem(value: 'INTACT', child: Text('Intact & Undamaged')),
            DropdownMenuItem(value: 'CRUSHED', child: Text('Crushed / Dented Box')),
            DropdownMenuItem(value: 'TORN', child: Text('Torn / Partially Opened')),
            DropdownMenuItem(value: 'TAMPERED', child: Text('Resealed or Tampered Tape')),
            DropdownMenuItem(value: 'WET', child: Text('Water / Liquid Damaged')),
          ],
          onChanged: (val) {
            if (val != null) {
              setState(() => _packageCondition = val);
              _notify();
            }
          },
        ),
        const SizedBox(height: 14),
        const Text(
          'Delivery Carrier (Optional)',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: AppColors.darkNeutral,
          ),
        ),
        const SizedBox(height: 6),
        TextField(
          controller: _carrierController,
          decoration: const InputDecoration(hintText: 'e.g. FedEx, UPS, DHL, BlueDart'),
          onChanged: (_) => _notify(),
        ),
        const SizedBox(height: 14),
        const Text(
          'Tracking Number (Optional)',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: AppColors.darkNeutral,
          ),
        ),
        const SizedBox(height: 6),
        TextField(
          controller: _trackingController,
          decoration: const InputDecoration(hintText: 'e.g. 1Z9999999999999999'),
          onChanged: (_) => _notify(),
        ),
      ],
    );
  }
}
