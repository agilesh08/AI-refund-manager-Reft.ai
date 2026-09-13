import 'package:flutter/material.dart';
import '../../../core/constants/app_colors.dart';
import '../../../models/workflow_step.dart';

/// Text input dynamic workflow step widget.
class TextStepWidget extends StatefulWidget {
  final WorkflowStepItem step;
  final String? initialValue;
  final ValueChanged<String> onChanged;

  const TextStepWidget({
    super.key,
    required this.step,
    this.initialValue,
    required this.onChanged,
  });

  @override
  State<TextStepWidget> createState() => _TextStepWidgetState();
}

class _TextStepWidgetState extends State<TextStepWidget> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialValue ?? '');
  }

  @override
  void didUpdateWidget(TextStepWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.initialValue != oldWidget.initialValue &&
        widget.initialValue != _controller.text) {
      _controller.text = widget.initialValue ?? '';
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final placeholder =
        widget.step.placeholder ?? 'Please describe the issue in detail...';
    final maxLength = widget.step.maxLength ?? 1000;

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
        TextField(
          controller: _controller,
          maxLines: 5,
          maxLength: maxLength,
          onChanged: widget.onChanged,
          decoration: InputDecoration(
            hintText: placeholder,
            alignLabelWithHint: true,
          ),
        ),
      ],
    );
  }
}
