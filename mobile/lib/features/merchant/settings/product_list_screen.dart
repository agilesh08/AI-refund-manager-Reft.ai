import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../../core/constants/app_colors.dart';
import '../../../core/network/api_exception.dart';
import '../../../services/merchant_service.dart';

/// Screen displaying merchant products with trusted reference evidence status.
class ProductListScreen extends StatefulWidget {
  const ProductListScreen({super.key});

  @override
  State<ProductListScreen> createState() => _ProductListScreenState();
}

class _ProductListScreenState extends State<ProductListScreen> {
  final MerchantService _merchantService = MerchantService();
  List<Map<String, dynamic>> _products = [];
  final Map<String, Map<String, dynamic>> _completenessMap = {};
  bool _isLoading = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _loadProducts();
  }

  Future<void> _loadProducts() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final products = await _merchantService.listProducts();
      final completenessResults = await Future.wait(
        products.map((p) async {
          final pId = p['id']?.toString() ?? '';
          if (pId.isEmpty) return null;
          try {
            final comp = await _merchantService.getProductCompleteness(pId);
            return MapEntry(pId, comp);
          } catch (_) {
            return null;
          }
        }),
      );

      final compMap = <String, Map<String, dynamic>>{};
      for (final entry in completenessResults) {
        if (entry != null) {
          compMap[entry.key] = entry.value;
        }
      }

      if (mounted) {
        setState(() {
          _products = products;
          _completenessMap.addAll(compMap);
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
            _errorMessage =
                'Failed to load products. Please check your network connection.';
          }
        });
      }
    }
  }

  void _showAddProductDialog() {
    final nameCtrl = TextEditingController();
    final skuCtrl = TextEditingController();
    final descCtrl = TextEditingController();
    final priceCtrl = TextEditingController();
    final formKey = GlobalKey<FormState>();
    bool isSaving = false;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (context, setDialogState) {
          return AlertDialog(
            title: const Text('Add New Product'),
            content: SingleChildScrollView(
              child: Form(
                key: formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextFormField(
                      controller: nameCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Product Name *',
                        hintText: 'e.g. Wireless Bluetooth Headphones',
                      ),
                      validator: (v) => (v == null || v.trim().isEmpty)
                          ? 'Please enter product name'
                          : null,
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: skuCtrl,
                      decoration: const InputDecoration(
                        labelText: 'SKU *',
                        hintText: 'e.g. HEADPHONE-PRO-01',
                      ),
                      validator: (v) => (v == null || v.trim().isEmpty)
                          ? 'Please enter product SKU'
                          : null,
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: priceCtrl,
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true),
                      decoration: const InputDecoration(
                        labelText: 'Price (₹)',
                        hintText: 'e.g. 799.00',
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: descCtrl,
                      maxLines: 2,
                      decoration: const InputDecoration(
                        labelText: 'Description (Optional)',
                        hintText: 'Key visual specifications',
                      ),
                    ),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: isSaving ? null : () => Navigator.pop(ctx),
                child: const Text('Cancel'),
              ),
              ElevatedButton(
                onPressed: isSaving
                    ? null
                    : () async {
                        if (!formKey.currentState!.validate()) return;
                        setDialogState(() => isSaving = true);
                        try {
                          double? price;
                          if (priceCtrl.text.trim().isNotEmpty) {
                            price = double.tryParse(priceCtrl.text.trim());
                          }
                          await _merchantService.createProduct(
                            name: nameCtrl.text.trim(),
                            sku: skuCtrl.text.trim(),
                            description: descCtrl.text.trim(),
                            price: price,
                          );
                          if (ctx.mounted) Navigator.pop(ctx);
                          _loadProducts();
                        } catch (e) {
                          setDialogState(() => isSaving = false);
                          if (ctx.mounted) {
                            String msg = 'Failed to create product.';
                            if (e is ApiException) msg = e.userMessage;
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text(msg),
                                backgroundColor:
                                    AppColors.assessmentInconsistent,
                              ),
                            );
                          }
                        }
                      },
                child: isSaving
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Add Product'),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildCompletenessBadge(Map<String, dynamic>? comp) {
    if (comp == null) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: Colors.grey.shade100,
          borderRadius: BorderRadius.circular(6),
        ),
        child: const Text(
          'Checking...',
          style: TextStyle(fontSize: 11, color: AppColors.textMuted),
        ),
      );
    }

    final isComplete = comp['is_complete'] == true || comp['complete'] == true;
    final count = comp['existing_count'] ??
        (isComplete
            ? 4
            : (comp['missing_angles'] is List
                ? (4 - (comp['missing_angles'] as List).length).clamp(0, 4)
                : 0));
    final requiredCount = comp['required_count'] ?? 4;

    if (isComplete) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: AppColors.assessmentConsistentBg,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
              color: AppColors.assessmentConsistent.withValues(alpha: 0.3)),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.check_circle_rounded,
                size: 13, color: AppColors.assessmentConsistent),
            SizedBox(width: 4),
            Text(
              'Trusted Evidence Complete (4/4)',
              style: TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w700,
                color: AppColors.assessmentConsistent,
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: AppColors.assessmentReviewRequiredBg,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(
            color: AppColors.assessmentReviewRequired.withValues(alpha: 0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.warning_amber_rounded,
              size: 13, color: AppColors.assessmentReviewRequired),
          const SizedBox(width: 4),
          Text(
            'Trusted Evidence ($count/$requiredCount angles)',
            style: const TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: AppColors.assessmentReviewRequired,
            ),
          ),
        ],
      ),
    );
  }

  void _showDeleteProductDialog(Map<String, dynamic> product) {
    final pId = product['id']?.toString() ?? '';
    final name = product['name']?.toString() ?? 'Product';
    if (pId.isEmpty) return;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete Product?'),
        content: Text(
          'Are you sure you want to delete "$name"? This will remove all associated reference images.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.assessmentInconsistent,
            ),
            onPressed: () async {
              Navigator.pop(ctx);
              try {
                await _merchantService.deleteProduct(pId);
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Deleted product "$name"')),
                  );
                }
                _loadProducts();
              } catch (e) {
                if (mounted) {
                  String msg = 'Failed to delete product.';
                  if (e is ApiException) msg = e.userMessage;
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(msg),
                      backgroundColor: AppColors.assessmentInconsistent,
                    ),
                  );
                }
              }
            },
            child: const Text('Delete', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          tooltip: 'Back to Settings',
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/settings');
            }
          },
        ),
        title: const Text('Trusted Product Evidence'),
        actions: [
          IconButton(
            icon: const Icon(Icons.add_rounded),
            tooltip: 'Add Product',
            onPressed: _showAddProductDialog,
          ),
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh',
            onPressed: _loadProducts,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _showAddProductDialog,
        icon: const Icon(Icons.add_rounded),
        label: const Text('New Product'),
      ),
      body: RefreshIndicator(
        onRefresh: _loadProducts,
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
                              size: 48, color: AppColors.assessmentInconsistent),
                          const SizedBox(height: 12),
                          Text(
                            _errorMessage!,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                                fontSize: 14, color: AppColors.darkNeutral),
                          ),
                          const SizedBox(height: 16),
                          ElevatedButton(
                            onPressed: _loadProducts,
                            child: const Text('Retry'),
                          ),
                        ],
                      ),
                    ),
                  )
                : _products.isEmpty
                    ? Center(
                        child: Padding(
                          padding: const EdgeInsets.all(24),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.inventory_2_outlined,
                                  size: 56, color: AppColors.textMuted),
                              const SizedBox(height: 14),
                              const Text(
                                'No Products Registered',
                                style: TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.darkNeutral,
                                ),
                              ),
                              const SizedBox(height: 6),
                              const Text(
                                'Register a product to upload authentic 4-angle reference photos for visual comparison.',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                    fontSize: 13,
                                    color: AppColors.textSecondary),
                              ),
                              const SizedBox(height: 18),
                              ElevatedButton.icon(
                                onPressed: _showAddProductDialog,
                                icon: const Icon(Icons.add_rounded),
                                label: const Text('Add First Product'),
                              ),
                            ],
                          ),
                        ),
                      )
                    : ListView.builder(
                        padding: const EdgeInsets.fromLTRB(16, 16, 16, 80),
                        itemCount: _products.length,
                        itemBuilder: (context, index) {
                          final product = _products[index];
                          final pId = product['id']?.toString() ?? '';
                          final name =
                              product['name']?.toString() ?? 'Product';
                          final sku = product['sku']?.toString() ?? 'N/A';
                          final price = product['price'];
                          final completeness = _completenessMap[pId];

                          return Card(
                            margin: const EdgeInsets.only(bottom: 12),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                              side: BorderSide(color: Colors.grey.shade200),
                            ),
                            child: InkWell(
                              borderRadius: BorderRadius.circular(12),
                              onTap: () async {
                                await context.push(
                                  '/settings/products/$pId/references',
                                  extra: product,
                                );
                                _loadProducts();
                              },
                              onLongPress: () => _showDeleteProductDialog(product),
                              child: Padding(
                                padding: const EdgeInsets.all(16),
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      mainAxisAlignment:
                                          MainAxisAlignment.spaceBetween,
                                      children: [
                                        Expanded(
                                          child: Text(
                                            name,
                                            style: const TextStyle(
                                              fontSize: 15,
                                              fontWeight: FontWeight.w700,
                                              color: AppColors.darkNeutral,
                                            ),
                                          ),
                                        ),
                                        if (price != null)
                                          Text(
                                            '₹${price.toString()}',
                                            style: const TextStyle(
                                              fontSize: 14,
                                              fontWeight: FontWeight.w700,
                                              color: AppColors.primary,
                                            ),
                                          ),
                                      ],
                                    ),
                                    const SizedBox(height: 4),
                                    Text(
                                      'SKU: $sku',
                                      style: const TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.w500,
                                        color: AppColors.textSecondary,
                                      ),
                                    ),
                                    const SizedBox(height: 12),
                                    Row(
                                      mainAxisAlignment:
                                          MainAxisAlignment.spaceBetween,
                                      children: [
                                        _buildCompletenessBadge(completeness),
                                        Row(
                                          children: const [
                                            Text(
                                              'Manage Evidence',
                                              style: TextStyle(
                                                fontSize: 12,
                                                fontWeight: FontWeight.w600,
                                                color: AppColors.primary,
                                              ),
                                            ),
                                            SizedBox(width: 4),
                                            Icon(
                                              Icons.arrow_forward_ios_rounded,
                                              size: 11,
                                              color: AppColors.primary,
                                            ),
                                          ],
                                        ),
                                      ],
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          );
                        },
                      ),
      ),
    );
  }
}
