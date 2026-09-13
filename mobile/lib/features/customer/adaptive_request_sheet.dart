import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../../core/constants/app_colors.dart';
import '../../models/evidence_models.dart';

/// Bottom sheet dialog prompting customer for follow-up evidence.
class AdaptiveRequestSheet extends StatefulWidget {
  final CustomerEvidenceRequestModel request;
  final Function(String requestId, Uint8List bytes, String filename) onFulfill;
  final bool isSubmitting;

  const AdaptiveRequestSheet({
    super.key,
    required this.request,
    required this.onFulfill,
    this.isSubmitting = false,
  });

  @override
  State<AdaptiveRequestSheet> createState() => _AdaptiveRequestSheetState();
}

class _AdaptiveRequestSheetState extends State<AdaptiveRequestSheet> {
  final ImagePicker _picker = ImagePicker();
  Uint8List? _imageBytes;
  String? _filename;

  Future<void> _pickImage(ImageSource source) async {
    try {
      final photo = await _picker.pickImage(
        source: source,
        imageQuality: 85,
        maxWidth: 1920,
      );
      if (photo != null) {
        final bytes = await photo.readAsBytes();
        setState(() {
          _imageBytes = bytes;
          _filename = photo.name;
        });
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open camera: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: AppColors.assessmentReviewRequiredBg,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(
                  Icons.add_photo_alternate_rounded,
                  color: AppColors.assessmentReviewRequired,
                  size: 22,
                ),
              ),
              const SizedBox(width: 12),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Additional Information Requested',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.darkNeutral,
                      ),
                    ),
                    Text(
                      'Help us complete your verification faster',
                      style: TextStyle(
                        fontSize: 12,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppColors.surfaceVariant.withValues(alpha: 0.6),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.request.promptText,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppColors.darkNeutral,
                    height: 1.4,
                  ),
                ),
                if (widget.request.reason != null &&
                    widget.request.reason!.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text(
                    'Reason: ${widget.request.reason}',
                    style: const TextStyle(
                      fontSize: 12,
                      fontStyle: FontStyle.italic,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 16),
          if (_imageBytes == null) ...[
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () => _pickImage(ImageSource.camera),
                    icon: const Icon(Icons.camera_alt_rounded, size: 18),
                    label: const Text('Take Photo'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _pickImage(ImageSource.gallery),
                    icon: const Icon(Icons.photo_library_rounded, size: 18),
                    label: const Text('Gallery'),
                  ),
                ),
              ],
            ),
          ] else ...[
            Container(
              height: 180,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: AppColors.primary),
              ),
              clipBehavior: Clip.antiAlias,
              child: Image.memory(_imageBytes!, fit: BoxFit.contain),
            ),
            const SizedBox(height: 12),
            ElevatedButton(
              onPressed: widget.isSubmitting
                  ? null
                  : () {
                      widget.onFulfill(
                        widget.request.id,
                        _imageBytes!,
                        _filename ?? 'follow_up.jpg',
                      );
                    },
              child: widget.isSubmitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                      ),
                    )
                  : const Text('Upload Follow-Up Evidence'),
            ),
          ],
        ],
      ),
    );
  }
}
