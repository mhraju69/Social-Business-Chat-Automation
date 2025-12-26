# permissions_config.py
from rest_framework.permissions import BasePermission

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

class IsAdmin(BasePermission):
    """Allow access only to admin users (is_staff=True AND is_superuser=True AND role='admin')."""
    def has_permission(self, request, view):
        return bool(
            request.user 
            and request.user.is_authenticated 
            and request.user.role == 'admin'
            and request.user.is_staff 
            and request.user.is_superuser
        )


class IsOwner(BasePermission):
    """Allow access only to owners."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and (request.user.is_owner or request.user.is_employee))


class IsEmployee(BasePermission):
    """Allow access only to employees."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_employee)


class IsOwnerOrEmployee(BasePermission):
    """Allow access to admins or owners."""
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_employee or request.user.is_owner)
        )

class IsEmployeeAndCanViewDashboard(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        # Only check if the user is an employee
        if hasattr(user, 'employee'):
            return user.employee.can_view_dashboard()
        # Non-employees have full access
        return True


class IsEmployeeAndCanManageUsers(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if hasattr(user, 'employee'):
            return user.employee.can_manage_users()
        return True


class IsEmployeeAndCanAccessFinancialData(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if hasattr(user, 'employee'):
            return user.employee.can_access_financial_data()
        return True


class IsEmployeeAndCanAccessCustomerSupport(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if hasattr(user, 'employee'):
            return user.employee.can_access_customer_support()
        return True


class IsEmployeeAndCanAccessBillingInvoices(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if hasattr(user, 'employee'):
            return user.employee.can_access_billing_invoices()
        return True


class IsEmployeeAndCanAccessAnalyticsReports(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if hasattr(user, 'employee'):
            return user.employee.can_access_analytics_reports()
        return True


class IsEmployeeAndCanAccessSystemSettings(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if hasattr(user, 'employee'):
            return user.employee.can_access_system_settings()
        return True


class IsEmployeeAndCanManageAPI(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if hasattr(user, 'employee'):
            return user.employee.can_manage_api()
        return True
