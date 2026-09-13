import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import '../../../core/constants/app_colors.dart';
import '../../../core/network/api_exception.dart';
import '../../../services/merchant_service.dart';

/// Screen managing authentic 4-angle trusted reference evidence for a product.
class ProductReferenceEvidenceScreen extends StatefulWidget {
  final String productId;
  final Map<String, dynamic>? initialProduct;

  const ProductReferenceEvidenceScreen({
    super.key,
    required this.productId,
    this.initialProduct,
  });

  @override
  State<ProductReferenceEvidenceScreen> createState() =>
      _ProductReferenceEvidenceScreenState();
}

class _ProductReferenceEvidenceScreenState
    extends State<ProductReferenceEvidenceScreen> {
  final MerchantService _merchantService = MerchantService();
  final ImagePicker _picker = ImagePicker();

  Map<String, dynamic>? _product;
  List<Map<String, dynamic>> _references = [];
  Map<String, dynamic>? _completeness;
  final Map<String, Uint8List> _previewBytes = {};

  bool _isLoading = true;
  String? _uploadingAngle;
  String? _errorMessage;

  static const List<Map<String, String>> _canonicalAngles = [
    {
      'angle': 'FRONT',
      'title': 'Front View',
      'desc': 'Direct front surface, brand logos, display, and key controls.',
    },
    {
      'angle': 'BACK',
      'title': 'Back View',
      'desc': 'Rear surface, serial labels, ports, and regulatory markings.',
    },
    {
      'angle': 'LEFT',
      'title': 'Left Side',
      'desc': 'Left profile, seams, structural edges, and port layout.',
    },
    {
      'angle': 'RIGHT',
      'title': 'Right Side',
      'desc': 'Right profile, buttons, hinges, and finish texture.',
    },
  ];

  @override
  void initState() {
    super.initState();
    _product = widget.initialProduct;
    _loadEvidenceData();
  }

  Future<void> _loadEvidenceData() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final futures = await Future.wait([
        _merchantService.listProductReferences(widget.productId),
        _merchantService.getProductCompleteness(widget.productId),
      ]);

      final refs = futures[0] as List<Map<String, dynamic>>;
      final comp = futures[1] as Map<String, dynamic>;

      // Load preview image bytes for existing angles
      final bytesMap = <String, Uint8List>{};
      await Future.wait(
        refs.map((r) async {
          final angle = r['angle']?.toString().toUpperCase();
          if (angle != null && angle.isNotEmpty) {
            try {
              final bytes = await _merchantService.getReferenceImageBytes(
                widget.productId,
                angle,
              );
              bytesMap[angle] = bytes;
            } catch (_) {
              // Ignore preview fetch failure, will show placeholder
            }
          }
        }),
      );

      if (mounted) {
        setState(() {
          _references = refs;
          _completeness = comp;
          _previewBytes.addAll(bytesMap);
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          if (e is ApiException) {
            _errorMessage = e.userMessage;
          } else {
            _errorMessage = 'Failed to load product reference data.';
          }
        });
      }
    }
  }

  Future<void> _pickAndUpload(String angle, {bool isReplace = false}) async {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.camera_alt_rounded,
                    color: AppColors.primary),
                title: const Text('Take Photo with Camera'),
                onTap: () {
                  Navigator.pop(ctx);
                  _processImagePick(angle, ImageSource.camera, isReplace);
                },
              ),
              ListTile(
                leading: const Icon(Icons.photo_library_rounded,
                    color: AppColors.primary),
                title: const Text('Choose from Gallery'),
                onTap: () {
                  Navigator.pop(ctx);
                  _processImagePick(angle, ImageSource.gallery, isReplace);
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _processImagePick(
      String angle, ImageSource source, bool isReplace) async {
    try {
      final XFile? photo = await _picker.pickImage(
        source: source,
        imageQuality: 88,
        maxWidth: 1920,
      );
      if (photo == null) return;

      setState(() => _uploadingAngle = angle);

      final bytes = await photo.readAsBytes();
      final filename = photo.name.isNotEmpty
          ? photo.name
          : '${angle.toLowerCase()}_ref.jpg';
      final mimeType =
          filename.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg';

      // If replacing, delete existing reference angle first
      if (isReplace) {
        try {
          await _merchantService.deleteProductReference(
            widget.productId,
            angle,
          );
        } catch (_) {}
      }

      await _merchantService.uploadProductReference(
        productId: widget.productId,
        angle: angle,
        fileBytes: bytes,
        filename: filename,
        mimeType: mimeType,
      );

      _previewBytes[angle] = bytes;
      await _loadEvidenceData();

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppColors.assessmentConsistent,
            content: Text('$angle angle reference uploaded successfully.'),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        String msg = 'Failed to upload reference image.';
        if (e is ApiException) msg = e.userMessage;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppColors.assessmentInconsistent,
            content: Text(msg),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _uploadingAngle = null);
      }
    }
  }

  Future<void> _confirmDelete(String angle) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Delete $angle Reference?'),
        content: Text(
          'Are you sure you want to remove the trusted $angle reference image? Without it, AI visual comparison will be incomplete.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.assessmentInconsistent,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      setState(() => _uploadingAngle = angle);
      try {
        await _merchantService.deleteProductReference(widget.productId, angle);
        _previewBytes.remove(angle);
        await _loadEvidenceData();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('$angle reference image removed.'),
            ),
          );
        }
      } catch (e) {
        if (mounted) {
          String msg = 'Failed to delete reference.';
          if (e is ApiException) msg = e.userMessage;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              backgroundColor: AppColors.assessmentInconsistent,
              content: Text(msg),
            ),
          );
        }
      } finally {
        if (mounted) {
          setState(() => _uploadingAngle = null);
        }
      }
    }
  }

  void _showImagePreviewDialog(String angle, Uint8List bytes) {
    showDialog(
      context: context,
      barrierColor: Colors.black.withValues(alpha: 0.92),
      builder: (ctx) => Scaffold(
        backgroundColor: Colors.transparent,
        body: SafeArea(
          child: Column(
            children: [
              // Dedicated Top Bar (Never overlaps the image)
              Container(
                color: Colors.black87,
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.verified_outlined,
                            size: 18, color: Colors.white70),
                        const SizedBox(width: 8),
                        Text(
                          '$angle Angle Reference',
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                    IconButton(
                      icon: const Icon(Icons.close_rounded,
                          color: Colors.white, size: 22),
                      tooltip: 'Close Preview',
                      onPressed: () => Navigator.pop(ctx),
                    ),
                  ],
                ),
              ),
              // Centered Image preview
              Expanded(
                child: Center(
                  child: InteractiveViewer(
                    maxScale: 4.0,
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Image.memory(
                        bytes,
                        fit: BoxFit.contain,
                      ),
                    ),
                  ),
                ),
              ),
              // Bottom angle & reference descriptor
              Container(
                width: double.infinity,
                padding:
                    const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                color: Colors.black87,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Official Reference Angle: $angle',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 3),
                    const Text(
                      'AI Visual reasoning performs comparative baseline analysis against this authentic photo.',
                      style: TextStyle(
                        color: Colors.white70,
                        fontSize: 12,
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

  Widget _buildCompletenessBanner() {
    final isComplete = _completeness?['complete'] == true ||
        _completeness?['is_complete'] == true ||
        _references.length >= 4;
    final count = isComplete
        ? 4
        : (_completeness?['existing_count'] ?? _references.length);

    if (isComplete) {
      return Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.assessmentConsistentBg,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
              color: AppColors.assessmentConsistent.withValues(alpha: 0.35)),
        ),
        child: const Row(
          children: [
            Icon(Icons.check_circle_rounded,
                color: AppColors.assessmentConsistent, size: 24),
            SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'READY FOR VISUAL VERIFICATION (4/4 ANGLES)',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: AppColors.assessmentConsistent,
                    ),
                  ),
                  SizedBox(height: 2),
                  Text(
                    'All 4 authentic angles (Front, Back, Left, Right) are uploaded. Visual AI will compare customer proof against these baselines.',
                    style: TextStyle(
                      fontSize: 11,
                      color: AppColors.darkNeutral,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.assessmentReviewRequiredBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
            color: AppColors.assessmentReviewRequired.withValues(alpha: 0.35)),
      ),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded,
              color: AppColors.assessmentReviewRequired, size: 24),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'TRUSTED EVIDENCE INCOMPLETE ($count/4 ANGLES)',
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: AppColors.assessmentReviewRequired,
                  ),
                ),
                const SizedBox(height: 2),
                const Text(
                  'Upload all 4 canonical angles to enable high-confidence automated AI visual verification.',
                  style: TextStyle(
                    fontSize: 11,
                    color: AppColors.darkNeutral,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAngleCard(Map<String, String> angleDef) {
    final angle = angleDef['angle']!;
    final title = angleDef['title']!;
    final desc = angleDef['desc']!;

    final isUploaded = _references.any(
        (r) => r['angle']?.toString().toUpperCase() == angle.toUpperCase());
    final isAngleBusy = _uploadingAngle == angle;
    final bytes = _previewBytes[angle];

    return Card(
      margin: const EdgeInsets.only(bottom: 14),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: isUploaded ? Colors.grey.shade300 : Colors.grey.shade200,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header: Title & Status Chip
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: AppColors.primaryLight,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        angle,
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w800,
                          color: AppColors.primary,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: AppColors.darkNeutral,
                      ),
                    ),
                  ],
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: isUploaded
                        ? AppColors.assessmentConsistentBg
                        : Colors.grey.shade100,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isUploaded
                            ? Icons.check_circle_rounded
                            : Icons.radio_button_unchecked_rounded,
                        size: 11,
                        color: isUploaded
                            ? AppColors.assessmentConsistent
                            : AppColors.textMuted,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        isUploaded ? 'Uploaded' : 'Missing',
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: isUploaded
                              ? AppColors.assessmentConsistent
                              : AppColors.textMuted,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              desc,
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.textSecondary,
              ),
            ),
            const SizedBox(height: 12),

            // Thumbnail / Loading indicator
            if (isAngleBusy)
              Container(
                height: 120,
                decoration: BoxDecoration(
                  color: Colors.grey.shade50,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.grey.shade200),
                ),
                child: const Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      CircularProgressIndicator(strokeWidth: 2),
                      SizedBox(height: 8),
                      Text('Processing image...',
                          style: TextStyle(
                              fontSize: 11, color: AppColors.textSecondary)),
                    ],
                  ),
                ),
              )
            else if (isUploaded && bytes != null)
              GestureDetector(
                onTap: () => _showImagePreviewDialog(angle, bytes),
                child: Container(
                  height: 140,
                  width: double.infinity,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.grey.shade300),
                  ),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: Stack(
                      fit: StackFit.expand,
                      children: [
                        Image.memory(
                          bytes,
                          fit: BoxFit.cover,
                        ),
                        Positioned(
                          right: 8,
                          bottom: 8,
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 4),
                            decoration: BoxDecoration(
                              color: Colors.black.withValues(alpha: 0.65),
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: const Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(Icons.zoom_in_rounded,
                                    size: 13, color: Colors.white),
                                SizedBox(width: 4),
                                Text(
                                  'Tap to view',
                                  style: TextStyle(
                                    fontSize: 10,
                                    color: Colors.white,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              )
            else if (isUploaded && bytes == null)
              Container(
                height: 80,
                decoration: BoxDecoration(
                  color: Colors.grey.shade50,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.grey.shade200),
                ),
                child: const Center(
                  child: Text(
                    'Reference uploaded (preview loading...)',
                    style: TextStyle(
                      fontSize: 12,
                      color: AppColors.textMuted,
                    ),
                  ),
                ),
              ),

            const SizedBox(height: 10),

            // Action Buttons
            if (!isUploaded)
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                  onPressed: isAngleBusy
                      ? null
                      : () => _pickAndUpload(angle, isReplace: false),
                  icon: const Icon(Icons.cloud_upload_outlined, size: 16),
                  label: Text('Upload $title'),
                ),
              )
            else
              Row(
                children: [
                  if (bytes != null)
                    Expanded(
                      child: OutlinedButton.icon(
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(8),
                          ),
                        ),
                        onPressed: () => _showImagePreviewDialog(angle, bytes),
                        icon: const Icon(Icons.visibility_outlined, size: 15),
                        label: const Text('View'),
                      ),
                    ),
                  if (bytes != null) const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                      onPressed: isAngleBusy
                          ? null
                          : () => _pickAndUpload(angle, isReplace: true),
                      icon: const Icon(Icons.refresh_rounded, size: 15),
                      label: const Text('Replace'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    icon: const Icon(Icons.delete_outline_rounded,
                        color: AppColors.assessmentInconsistent, size: 20),
                    tooltip: 'Delete $angle reference',
                    onPressed: isAngleBusy ? null : () => _confirmDelete(angle),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final productName = _product?['name']?.toString() ?? 'Product';
    final productSku = _product?['sku']?.toString() ?? '';

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          tooltip: 'Back to Products',
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/settings/products');
            }
          },
        ),
        title: const Text('Trusted Product Evidence'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh',
            onPressed: _loadEvidenceData,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadEvidenceData,
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _errorMessage != null
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(Icons.error_outline_rounded,
                              size: 48,
                              color: AppColors.assessmentInconsistent),
                          const SizedBox(height: 12),
                          Text(_errorMessage!,
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                  fontSize: 14, color: AppColors.darkNeutral)),
                          const SizedBox(height: 16),
                          ElevatedButton(
                            onPressed: _loadEvidenceData,
                            child: const Text('Retry'),
                          ),
                        ],
                      ),
                    ),
                  )
                : ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      // Product summary card
                      Container(
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: AppColors.primaryLight.withValues(alpha: 0.25),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                              color: AppColors.primary.withValues(alpha: 0.25)),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.inventory_2_rounded,
                                color: AppColors.primary, size: 22),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    productName,
                                    style: const TextStyle(
                                      fontSize: 15,
                                      fontWeight: FontWeight.w700,
                                      color: AppColors.darkNeutral,
                                    ),
                                  ),
                                  if (productSku.isNotEmpty)
                                    Text(
                                      'SKU: $productSku',
                                      style: const TextStyle(
                                        fontSize: 12,
                                        color: AppColors.textSecondary,
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 14),

                      // Explainer Banner
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                        decoration: BoxDecoration(
                          color: AppColors.primaryLight.withValues(alpha: 0.35),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                              color: AppColors.primary.withValues(alpha: 0.25)),
                        ),
                        child: const Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(Icons.verified_user_outlined,
                                color: AppColors.primary, size: 20),
                            SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Trusted Product Evidence',
                                    style: TextStyle(
                                      fontSize: 13,
                                      fontWeight: FontWeight.w700,
                                      color: AppColors.darkNeutral,
                                    ),
                                  ),
                                  SizedBox(height: 2),
                                  Text(
                                    'These reference images represent the legitimate product used during visual verification. Customer photos are checked against these authentic baselines.',
                                    style: TextStyle(
                                      fontSize: 11.5,
                                      height: 1.35,
                                      color: AppColors.textSecondary,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 14),

                      // Completeness Indicator
                      _buildCompletenessBanner(),
                      const SizedBox(height: 18),

                      // Section Header
                      const Text(
                        '4 Canonical Reference Angles',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.darkNeutral,
                        ),
                      ),
                      const SizedBox(height: 10),

                      // 4 Canonical Angle Cards
                      ..._canonicalAngles.map((def) => _buildAngleCard(def)),
                    ],
                  ),
      ),
    );
  }
}
