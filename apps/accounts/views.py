from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render
from django.views import View

from .forms import LoginForm, RegisterForm
from .models import Empresa, Membership


class CustomLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("/")
        form = RegisterForm()
        return render(request, "accounts/register.html", {"form": form})

    def post(self, request):
        form = RegisterForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                from .models import User

                user = User.objects.create_user(
                    email=form.cleaned_data["email"],
                    full_name=form.cleaned_data["full_name"],
                    password=form.cleaned_data["password"],
                )
                empresa = Empresa.objects.create(
                    name=form.cleaned_data["empresa_name"],
                    segment=form.cleaned_data["segment"],
                )
                Membership.objects.create(
                    user=user,
                    empresa=empresa,
                    role=Membership.Role.OWNER,
                )
                user.active_empresa = empresa
                user.save(update_fields=["active_empresa"])

                # Create default pipeline for the empresa
                from apps.crm.models import Pipeline, PipelineStage

                pipeline = Pipeline.objects.create(
                    empresa=empresa,
                    name="Pipeline Principal",
                    is_default=True,
                )
                default_stages = [
                    ("Prospecção", 0, "#6366F1"),
                    ("Qualificação", 1, "#8B5CF6"),
                    ("Proposta", 2, "#F59E0B"),
                    ("Negociação", 3, "#F97316"),
                    ("Fechado/Ganho", 4, "#10B981"),
                    ("Fechado/Perdido", 5, "#EF4444"),
                ]
                for name, order, color in default_stages:
                    PipelineStage.objects.create(
                        pipeline=pipeline,
                        name=name,
                        order=order,
                        color=color,
                        is_won=(name == "Fechado/Ganho"),
                        is_lost=(name == "Fechado/Perdido"),
                    )

                # Create default financial categories
                from apps.finance.models import FinancialCategory

                for cat_name, cat_type in [
                    ("Serviços", "income"),
                    ("Consultoria", "income"),
                    ("Produtos", "income"),
                    ("Outros Recebimentos", "income"),
                    ("Salários", "expense"),
                    ("Aluguel", "expense"),
                    ("Material", "expense"),
                    ("Transporte", "expense"),
                    ("Impostos", "expense"),
                    ("Outros Gastos", "expense"),
                ]:
                    FinancialCategory.objects.create(
                        empresa=empresa,
                        name=cat_name,
                        type=cat_type,
                    )

                login(request, user)
                messages.success(request, f"Bem-vindo ao sistema, {user.first_name_display}!")
                return redirect("/")

        return render(request, "accounts/register.html", {"form": form})


class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect("/accounts/login/")

    def get(self, request):
        logout(request)
        return redirect("/accounts/login/")
