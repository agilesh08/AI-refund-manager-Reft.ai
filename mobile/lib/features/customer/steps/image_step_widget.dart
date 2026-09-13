import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../../../core/constants/app_colors.dart';
import '../../../models/workflow_step.dart';

/// Camera/Image capture dynamic workflow step widget supporting up to 3 initial product images.
class ImageStepWidget extends StatefulWidget {
  final WorkflowStepItem step;
  final Uint8List? selectedImageBytes;
  final String? filename;
  final List<Uint8List>? initialImages;
  final List<String>? initialFilenames;
  final bool isUploading;
  final Function(Uint8List bytes, String filename) onImagePicked;
  final VoidCallback? onImageRemoved;
  final void Function(List<Uint8List> images, List<String> filenames)?
      onImagesChanged;

  const ImageStepWidget({
    super.key,
    required this.step,
    this.selectedImageBytes,
    this.filename,
    this.initialImages,
    this.initialFilenames,
    this.isUploading = false,
    required this.onImagePicked,
    this.onImageRemoved,
    this.onImagesChanged,
  });

  @override
  State<ImageStepWidget> createState() => _ImageStepWidgetState();
}

class _ImageStepWidgetState extends State<ImageStepWidget> {
  final ImagePicker _picker = ImagePicker();
  final List<Uint8List> _images = [];
  final List<String> _filenames = [];

  @override
  void initState() {
    super.initState();
    if (widget.initialImages != null && widget.initialImages!.isNotEmpty) {
      _images.addAll(widget.initialImages!);
      if (widget.initialFilenames != null) {
        _filenames.addAll(widget.initialFilenames!);
      }
    } else if (widget.selectedImageBytes != null) {
      _images.add(widget.selectedImageBytes!);
      _filenames.add(widget.filename ?? 'evidence_1.jpg');
    }
  }

  Future<void> _pickImage(ImageSource source) async {
    if (_images.length >= 3) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Maximum initial evidence reached (3/3).'),
        ),
      );
      return;
    }

    try {
      final XFile? photo = await _picker.pickImage(
        source: source,
        imageQuality: 85,
        maxWidth: 1920,
        maxHeight: 1920,
      );
      if (photo != null) {
        final bytes = await photo.readAsBytes();
        setState(() {
          _images.add(bytes);
          _filenames.add(photo.name);
        });
        widget.onImagePicked(bytes, photo.name);
        widget.onImagesChanged?.call(_images, _filenames);
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not access camera: ')),
      );
    }
  }

  void _removeImage(int index) {
    if (index >= 0 && index < _images.length) {
      setState(() {
        _images.removeAt(index);
        _filenames.removeAt(index);
      });
      widget.onImagesChanged?.call(_images, _filenames);
      if (_images.isEmpty) {
        widget.onImageRemoved?.call();
      }
    }
  }

  Widget _buildPhotographyTips() {
    return Container(
      margin: const EdgeInsets.only(bottom: 18),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.primaryLight.withValues(alpha: 0.28),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.primary.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.lightbulb_outline_rounded,
                  color: AppColors.primary, size: 20),
              SizedBox(width: 8),
              Text(
                'Photo Verification Instructions',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: AppColors.darkNeutral,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _buildTipItem(
            Icons.crop_free_rounded,
            '1. Keep entire product visible in the frame',
          ),
          _buildTipItem(
            Icons.wb_sunny_outlined,
            '2. Ensure good lighting and avoid glare',
          ),
          _buildTipItem(
            Icons.center_focus_strong_outlined,
            '3. Focus on the specific damage or issue',
          ),
          _buildTipItem(
            Icons.camera_enhance_outlined,
            '4. Keep the device steady while taking the photo',
          ),
        ],
      ),
    );
  }

  Widget _buildTipItem(IconData icon, String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: AppColors.primary),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                fontSize: 13,
                color: AppColors.darkNeutral,
                height: 1.3,
              ),
            ),
          ),
        ],
      ),
    );
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
        if (_images.isEmpty) ...[
          _buildPhotographyTips(),
          Container(
            padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 20),
            decoration: BoxDecoration(
              color: AppColors.surfaceVariant.withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: AppColors.primary.withValues(alpha: 0.4),
                style: BorderStyle.solid,
                width: 1.5,
              ),
            ),
            child: Column(
              children: [
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: AppColors.primaryLight.withValues(alpha: 0.5),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.add_a_photo_rounded,
                    size: 36,
                    color: AppColors.primary,
                  ),
                ),
                const SizedBox(height: 14),
                const Text(
                  'Camera required',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: AppColors.darkNeutral,
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  'Live camera photo required for proof verification. (Up to 3 images)',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 12,
                    color: AppColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 20),
                ElevatedButton.icon(
                  onPressed: () => _pickImage(ImageSource.camera),
                  icon: const Icon(Icons.camera_alt_rounded, size: 20),
                  label: const Text('Open Camera & Capture Proof'),
                  style: ElevatedButton.styleFrom(
                    minimumSize: const Size(double.infinity, 48),
                  ),
                ),
              ],
            ),
          ),
        ] else ...[
          ...List.generate(_images.length, (index) {
            final imgBytes = _images[index];
            final imgName = _filenames.length > index
                ? _filenames[index]
                : 'Evidence ${index + 1}';
            return Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.border),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.02),
                    blurRadius: 6,
                    offset: const Offset(0, 2),
                  ),
                ],
              ),
              child: Row(
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: Image.memory(
                      imgBytes,
                      width: 72,
                      height: 72,
                      fit: BoxFit.cover,
                      cacheWidth: 144,
                      cacheHeight: 144,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Evidence ${index + 1}',
                          style: const TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          imgName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 11.5,
                            color: AppColors.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    onPressed: () => _removeImage(index),
                    icon: const Icon(Icons.delete_outline_rounded,
                        color: AppColors.assessmentInconsistent, size: 20),
                    tooltip: 'Remove',
                  ),
                ],
              ),
            );
          }),
          const SizedBox(height: 8),
          if (_images.length < 3) ...[
            OutlinedButton.icon(
              onPressed: () => _pickImage(ImageSource.camera),
              icon: const Icon(Icons.add_a_photo_outlined, size: 18),
              label: Text('+ Add Evidence (${_images.length}/3)'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 13),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10)),
              ),
            ),
          ] else ...[
            Container(
              padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
              decoration: BoxDecoration(
                color: AppColors.assessmentConsistentBg,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: AppColors.assessmentConsistent.withValues(alpha: 0.35),
                ),
              ),
              child: const Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.check_circle_outline_rounded,
                      size: 16, color: AppColors.assessmentConsistent),
                  SizedBox(width: 8),
                  Text(
                    'Maximum initial evidence reached',
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w700,
                      color: AppColors.assessmentConsistent,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ],
    );
  }
}
