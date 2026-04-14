from django.urls import path

from . import views

app_name = "settings_app"

urlpatterns = [
    # Index
    path("", views.SettingsIndexView.as_view(), name="index"),
    # Service Types
    path(
        "service-types/",
        views.ServiceTypeListView.as_view(),
        name="service_type_list",
    ),
    path(
        "service-types/create/",
        views.ServiceTypeCreateView.as_view(),
        name="service_type_create",
    ),
    path(
        "service-types/<int:pk>/edit/",
        views.ServiceTypeUpdateView.as_view(),
        name="service_type_update",
    ),
    path(
        "service-types/<int:pk>/delete/",
        views.ServiceTypeDeleteView.as_view(),
        name="service_type_delete",
    ),
    # Pipeline Stages
    path(
        "pipeline-stages/",
        views.PipelineStagesView.as_view(),
        name="pipeline_stages",
    ),
    path(
        "pipeline-stages/create/",
        views.PipelineStageCreateView.as_view(),
        name="pipeline_stage_create",
    ),
    path(
        "pipeline-stages/<int:pk>/edit/",
        views.PipelineStageUpdateView.as_view(),
        name="pipeline_stage_update",
    ),
    path(
        "pipeline-stages/<int:pk>/delete/",
        views.PipelineStageDeleteView.as_view(),
        name="pipeline_stage_delete",
    ),
    # Proposal Templates
    path(
        "proposal-templates/",
        views.ProposalTemplatesView.as_view(),
        name="proposal_templates",
    ),
    path(
        "proposal-templates/create/",
        views.ProposalTemplateCreateView.as_view(),
        name="proposal_template_create",
    ),
    path(
        "proposal-templates/<int:pk>/edit/",
        views.ProposalTemplateUpdateView.as_view(),
        name="proposal_template_update",
    ),
    path(
        "proposal-templates/<int:pk>/delete/",
        views.ProposalTemplateDeleteView.as_view(),
        name="proposal_template_delete",
    ),
    # Contract Templates
    path(
        "contract-templates/",
        views.ContractTemplatesView.as_view(),
        name="contract_templates",
    ),
    path(
        "contract-templates/create/",
        views.ContractTemplateCreateView.as_view(),
        name="contract_template_create",
    ),
    path(
        "contract-templates/<int:pk>/edit/",
        views.ContractTemplateUpdateView.as_view(),
        name="contract_template_update",
    ),
    path(
        "contract-templates/<int:pk>/delete/",
        views.ContractTemplateDeleteView.as_view(),
        name="contract_template_delete",
    ),
    # Financial Categories
    path(
        "categories/",
        views.FinancialCategoryListView.as_view(),
        name="category_list",
    ),
    path(
        "categories/create/",
        views.FinancialCategoryCreateView.as_view(),
        name="category_create",
    ),
    path(
        "categories/<int:pk>/edit/",
        views.FinancialCategoryUpdateView.as_view(),
        name="category_update",
    ),
    path(
        "categories/<int:pk>/delete/",
        views.FinancialCategoryDeleteView.as_view(),
        name="category_delete",
    ),
    # Bank Accounts
    path(
        "bank-accounts/",
        views.BankAccountListView.as_view(),
        name="bank_account_list",
    ),
    path(
        "bank-accounts/create/",
        views.BankAccountCreateView.as_view(),
        name="bank_account_create",
    ),
    path(
        "bank-accounts/<int:pk>/edit/",
        views.BankAccountUpdateView.as_view(),
        name="bank_account_update",
    ),
    path(
        "bank-accounts/<int:pk>/delete/",
        views.BankAccountDeleteView.as_view(),
        name="bank_account_delete",
    ),
    # Teams
    path(
        "teams/",
        views.TeamListView.as_view(),
        name="team_list",
    ),
    path(
        "teams/create/",
        views.TeamCreateView.as_view(),
        name="team_create",
    ),
    path(
        "teams/<int:pk>/edit/",
        views.TeamUpdateView.as_view(),
        name="team_update",
    ),
    path(
        "teams/<int:pk>/delete/",
        views.TeamDeleteView.as_view(),
        name="team_delete",
    ),
    path(
        "teams/<int:pk>/members/add/",
        views.TeamMemberAddView.as_view(),
        name="team_member_add",
    ),
    path(
        "teams/<int:pk>/members/<int:member_pk>/remove/",
        views.TeamMemberRemoveView.as_view(),
        name="team_member_remove",
    ),
    path(
        "teams/<int:pk>/members/<int:member_pk>/role/",
        views.TeamMemberRoleView.as_view(),
        name="team_member_role",
    ),
    # WhatsApp Config
    path("whatsapp/", views.WhatsAppConfigView.as_view(), name="whatsapp_config"),
    path("whatsapp/save/", views.WhatsAppConfigSaveView.as_view(), name="whatsapp_config_save"),
    path("whatsapp/status/", views.WhatsAppStatusView.as_view(), name="whatsapp_status"),
]
