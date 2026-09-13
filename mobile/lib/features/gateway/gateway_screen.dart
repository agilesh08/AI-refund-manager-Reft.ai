import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/constants/api_endpoints.dart';
import '../../core/constants/app_colors.dart';
import '../../core/storage/token_storage.dart';

/// First-launch role selection gateway and customer link launcher.
class GatewayScreen extends StatefulWidget {
  const GatewayScreen({super.key});

  @override
  State<GatewayScreen> createState() => _GatewayScreenState();
}

class _GatewayScreenState extends State<GatewayScreen> {
  final TextEditingController _tokenController = TextEditingController();
  final TokenStorage _tokenStorage = TokenStorage();

  @override
  void initState() {
    super.initState();
    _checkSavedMode();
  }

  Future<void> _checkSavedMode() async {
    final token = await _tokenStorage.getToken();
    if (token != null && token.isNotEmpty) {
      if (mounted) {
        context.go('/dashboard');
        return;
      }
    }
  }

  void _submitToken() {
    String input = _tokenController.text.trim();
    if (input.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter a verification code or link')),
      );
      return;
    }

    // Extract token if user pasted a full URL
    if (input.contains('/verify/')) {
      input = input.split('/verify/').last.split('?').first.split('#').first;
    }

    _tokenStorage.setCustomerMode(true);
    context.go('/verify/$input');
  }

  void _showSettingsDialog() {
    final controller = TextEditingController(text: ApiEndpoints.baseUrl);
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('API Server Configuration'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Set the FastAPI backend URL (use 10.0.2.2 for Android emulator, or your local machine IP):',
              style: TextStyle(fontSize: 13, color: AppColors.textSecondary),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                labelText: 'Base URL',
                hintText: 'http://10.0.2.2:8000',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () async {
              final newUrl = controller.text.trim();
              if (newUrl.isNotEmpty) {
                ApiEndpoints.setBaseUrl(newUrl);
                await _tokenStorage.saveBaseUrl(ApiEndpoints.baseUrl);
              }
              if (ctx.mounted) Navigator.pop(ctx);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _tokenController.dispose();
    super.dispose();
  }

  Widget _buildFeaturePill(String emoji, String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: AppColors.surfaceVariant.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(emoji, style: const TextStyle(fontSize: 12)),
          const SizedBox(width: 5),
          Text(
            text,
            style: const TextStyle(
              fontSize: 11.5,
              fontWeight: FontWeight.w600,
              color: AppColors.darkNeutral,
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0.5,
        titleSpacing: 16,
        title: Row(
          children: [
            Image.asset(
              'assets/branding/reft_icon.png',
              width: 32,
              height: 32,
              fit: BoxFit.contain,
              semanticLabel: 'Reft.AI Logo',
            ),
            const SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text(
                  'Reft.AI',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: AppColors.primary,
                    letterSpacing: -0.2,
                  ),
                ),
                Text(
                  'Welcome back • Refund Verification',
                  style: TextStyle(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w500,
                    color: AppColors.textSecondary.withValues(alpha: 0.85),
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined, color: AppColors.darkNeutral, size: 22),
            tooltip: 'Server Settings',
            onPressed: _showSettingsDialog,
          ),
          IconButton(
            icon: const Icon(Icons.person_outline_rounded, color: AppColors.darkNeutral, size: 22),
            tooltip: 'Merchant Login',
            onPressed: () => context.push('/login'),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Centered Lock Icon Container
                  Center(
                    child: Container(
                      width: 68,
                      height: 68,
                      decoration: BoxDecoration(
                        color: AppColors.primaryLight.withValues(alpha: 0.35),
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: AppColors.primary.withValues(alpha: 0.2),
                          width: 1.5,
                        ),
                      ),
                      alignment: Alignment.center,
                      child: Image.asset(
                        'assets/branding/reft_icon.png',
                        width: 50,
                        height: 50,
                        fit: BoxFit.contain,
                        semanticLabel: 'Reft.AI',
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Brand & Subtitle
                  Center(
                    child: Image.asset(
                      'assets/branding/reft_wordmark.png',
                      width: 180,
                      fit: BoxFit.contain,
                      semanticLabel: 'Reft.AI',
                    ),
                  ),
                  const SizedBox(height: 4),
                  const Text(
                    'Customer Verification',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: AppColors.primary,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Securely verify your refund claim with a few simple steps.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w400,
                      color: AppColors.textSecondary,
                      height: 1.45,
                    ),
                  ),
                  const SizedBox(height: 18),

                  // Feature Pills Row
                  Wrap(
                    alignment: WrapAlignment.center,
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      _buildFeaturePill('📦', 'Order Check'),
                      _buildFeaturePill('📸', 'Photo Proof'),
                      _buildFeaturePill('✓', 'Fast Review'),
                    ],
                  ),
                  const SizedBox(height: 22),

                  // Card containing verification token entry
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: AppColors.border),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withValues(alpha: 0.04),
                          blurRadius: 14,
                          offset: const Offset(0, 4),
                        ),
                      ],
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Row(
                          children: [
                            Text('🔗', style: TextStyle(fontSize: 14)),
                            SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                'Enter verification code or link',
                                style: TextStyle(
                                  fontSize: 12.5,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.darkNeutral,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _tokenController,
                          decoration: InputDecoration(
                            hintText: 'e.g. VR-2026-XXXX or link',
                            hintStyle: const TextStyle(fontSize: 12.5),
                            prefixIcon: const Icon(Icons.vpn_key_outlined, size: 18),
                            contentPadding: const EdgeInsets.symmetric(
                                horizontal: 14, vertical: 12),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ),
                          onSubmitted: (_) => _submitToken(),
                        ),
                        const SizedBox(height: 16),
                        ElevatedButton(
                          onPressed: _submitToken,
                          style: ElevatedButton.styleFrom(
                            minimumSize: const Size(double.infinity, 46),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ),
                          child: const Text('Continue'),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Subtle merchant portal sign in link
                  Center(
                    child: TextButton.icon(
                      onPressed: () => context.push('/login'),
                      icon: const Icon(Icons.lock_outline_rounded, size: 14),
                      label: const Text(
                        'Merchant Portal Sign In',
                        style: TextStyle(fontSize: 12.5),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
