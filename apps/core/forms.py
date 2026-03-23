from django import forms


class TailwindFormMixin:
    """Mixin that injects Tailwind CSS classes into all form fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_class = (
            "block w-full rounded-lg border-slate-300 bg-white px-3 py-2 text-sm "
            "text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 "
            "placeholder:text-slate-400 "
            "focus:ring-2 focus:ring-inset focus:ring-indigo-600 focus:outline-none"
        )
        select_class = (
            "block w-full rounded-lg border-slate-300 bg-white px-3 py-2 text-sm "
            "text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 "
            "focus:ring-2 focus:ring-inset focus:ring-indigo-600 focus:outline-none"
        )
        checkbox_class = (
            "h-4 w-4 rounded border-slate-300 text-indigo-600 "
            "focus:ring-indigo-600"
        )
        textarea_class = base_class + " resize-none"

        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", checkbox_class)
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", textarea_class)
                widget.attrs.setdefault("rows", 3)
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", select_class)
            elif isinstance(widget, forms.FileInput):
                widget.attrs.setdefault("class", "block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100")
            else:
                widget.attrs.setdefault("class", base_class)
