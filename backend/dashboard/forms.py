from django import forms


class StorefrontOrderForm(forms.Form):
    name = forms.CharField(max_length=200, required=False, label="Имя")
    phone = forms.CharField(max_length=32, required=False, label="Телефон")
    email = forms.EmailField(required=False, label="Email")
    selected_product = forms.CharField(max_length=200, required=False, label="Товар")
    quantity = forms.IntegerField(min_value=1, required=False, label="Количество")
    free_text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
        label="Свободный текст заказа",
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("free_text") and not cleaned.get("selected_product"):
            raise forms.ValidationError(
                "Укажите товар карточкой или напишите заказ в свободной форме."
            )
        return cleaned

