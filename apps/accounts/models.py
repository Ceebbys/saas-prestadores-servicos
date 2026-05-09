from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimestampedModel


class UserManager(BaseUserManager):
    """Custom manager for email-based User model."""

    def create_user(self, email, full_name, password=None, **extra_fields):
        if not email:
            raise ValueError("O email é obrigatório")
        email = self.normalize_email(email)
        user = self.model(email=email, full_name=full_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, full_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, full_name, password, **extra_fields)


class User(AbstractUser):
    """Custom user model with email-based authentication."""

    username = None
    email = models.EmailField("E-mail", unique=True)
    full_name = models.CharField("Nome completo", max_length=255)
    phone = models.CharField("Telefone", max_length=20, blank=True)
    avatar = models.ImageField("Avatar", upload_to="avatars/", blank=True)
    active_empresa = models.ForeignKey(
        "Empresa",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Empresa ativa",
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

    def __str__(self):
        return self.full_name

    @property
    def first_name_display(self):
        return self.full_name.split()[0] if self.full_name else self.email

    @property
    def initials(self):
        parts = self.full_name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.full_name[:2].upper() if self.full_name else "?"


class Empresa(TimestampedModel):
    """Tenant model representing a company/workspace."""

    class Segment(models.TextChoices):
        TOPOGRAFIA = "topografia", "Topografia"
        ARQUITETURA = "arquitetura", "Arquitetura"
        ENGENHARIA = "engenharia", "Engenharia"
        MANUTENCAO = "manutencao", "Manutenção"
        CONSULTORIA = "consultoria", "Consultoria"
        INFORMATICA = "informatica", "Informática"
        SAUDE = "saude", "Saúde"
        JURIDICO = "juridico", "Jurídico"
        OUTRO = "outro", "Outro"

    name = models.CharField("Nome da empresa", max_length=255)
    slug = models.SlugField("Slug", unique=True, max_length=100)
    segment = models.CharField(
        "Segmento",
        max_length=50,
        choices=Segment.choices,
        default=Segment.OUTRO,
    )
    document = models.CharField("CNPJ", max_length=20, blank=True)
    logo = models.ImageField("Logo", upload_to="empresas/logos/", blank=True)
    email = models.EmailField("E-mail", blank=True)
    phone = models.CharField("Telefone", max_length=20, blank=True)
    address = models.TextField("Endereço", blank=True)
    settings = models.JSONField("Configurações", default=dict, blank=True)
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Empresa.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


class EmpresaEmailConfig(TimestampedModel):
    """Configuração SMTP por empresa.

    Quando configurada e ativa, sobrescreve o SMTP global para envios em nome
    desta empresa (propostas, notificações). Senha é armazenada criptografada
    com Fernet — `apps.core.encryption.encrypt/decrypt`.

    Fallback: se a empresa não tem config ou ela está inativa, usa o SMTP
    global do settings.
    """

    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        related_name="email_config",
        verbose_name="Empresa",
    )
    host = models.CharField("Servidor SMTP", max_length=200)
    port = models.PositiveIntegerField("Porta", default=587)
    username = models.CharField("Usuário", max_length=200)
    password_encrypted = models.TextField(
        "Senha (criptografada)", blank=True, editable=False,
    )
    use_tls = models.BooleanField("Usar TLS", default=True)
    use_ssl = models.BooleanField("Usar SSL", default=False)
    timeout_seconds = models.PositiveIntegerField(
        "Timeout (segundos)", default=20,
    )
    from_email = models.EmailField("E-mail de origem", max_length=200)
    from_name = models.CharField(
        "Nome de exibição",
        max_length=200,
        blank=True,
        help_text="Aparece como remetente. Em branco = nome da empresa.",
    )
    is_active = models.BooleanField(
        "Ativa",
        default=True,
        help_text="Desative para temporariamente cair no SMTP global.",
    )
    last_tested_at = models.DateTimeField(
        "Último teste", null=True, blank=True, editable=False,
    )
    last_test_ok = models.BooleanField(
        "Último teste OK", default=False, editable=False,
    )
    last_test_error = models.TextField(
        "Erro no último teste", blank=True, editable=False,
    )

    class Meta:
        verbose_name = "Configuração de E-mail"
        verbose_name_plural = "Configurações de E-mail"

    def __str__(self):
        return f"{self.empresa.name} — {self.from_email}"

    def set_password(self, plaintext: str):
        from apps.core.encryption import encrypt
        self.password_encrypted = encrypt(plaintext or "")

    def get_password(self) -> str:
        from apps.core.encryption import decrypt
        return decrypt(self.password_encrypted)

    def get_from_address(self) -> str:
        """Retorna 'Nome <email@dominio>' formatado."""
        name = (self.from_name or self.empresa.name or "").strip()
        if name:
            return f"{name} <{self.from_email}>"
        return self.from_email


class Membership(TimestampedModel):
    """Links a User to an Empresa with a specific role."""

    class Role(models.TextChoices):
        OWNER = "owner", "Proprietário"
        ADMIN = "admin", "Administrador"
        MANAGER = "manager", "Gerente"
        MEMBER = "member", "Membro"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="Usuário",
    )
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="Empresa",
    )
    role = models.CharField(
        "Papel",
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Membro"
        verbose_name_plural = "Membros"
        unique_together = ("user", "empresa")

    def __str__(self):
        return f"{self.user.full_name} - {self.empresa.name} ({self.get_role_display()})"
