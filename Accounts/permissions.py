# permissions_config.py

PERMISSIONS_MATRIX = {
    'owner': {
        'view_dashboard': True,
        'manage_users': True,
        'financial_data': True,
        'customer_support': False,
        'billing_invoices': True,
        'analytics_reports': False,
        'system_settings': True,
        'api_management': True,
    },
    'finance': {
        'view_dashboard': True,
        'manage_users': False,
        'financial_data': False,
        'customer_support': False,
        'billing_invoices': True,
        'analytics_reports': False,
        'system_settings': True,
        'api_management': False,
    },
    'support': {
        'view_dashboard': True,
        'manage_users': False,
        'financial_data': False,
        'customer_support': True,
        'billing_invoices': True,
        'analytics_reports': False,
        'system_settings': False,
        'api_management': True,
    },
    'analyst': {
        'view_dashboard': True,
        'manage_users': True,
        'financial_data': True,
        'customer_support': False,
        'billing_invoices': False,
        'analytics_reports': True,
        'system_settings': True,
        'api_management': False,
    },
    'read_only': {
        'view_dashboard': True,
        'manage_users': False,
        'financial_data': True,
        'customer_support': True,
        'billing_invoices': True,
        'analytics_reports': True,
        'system_settings': True,
        'api_management': True,
    }
}

# Valid roles
VALID_ROLES = list(PERMISSIONS_MATRIX.keys())

# Permission names for display
PERMISSION_NAMES = {
    'view_dashboard': 'View Dashboard',
    'manage_users': 'Manage Users',
    'financial_data': 'Financial Data',
    'customer_support': 'Customer Support',
    'billing_invoices': 'Billing & Invoices',
    'analytics_reports': 'Analytics & Reports',
    'system_settings': 'System Settings',
    'api_management': 'API Management',
}