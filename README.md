# Öğrenci Takımı için PR İnceleme Botu

Bot, pull request diffini Claude ile inceler. Türkçe özet, gerekçeli bulgular ve test önerileri üretir. GitHub'a yalnızca `COMMENT` incelemesi gönderir. Son karar ekip liderindedir. Python 3.10+ ve standart kütüphane yeterlidir.

## GitHub Actions kurulumu

1. Hedef deponun **Settings → Secrets and variables → Actions** bölümünde `ANTHROPIC_API_KEY` adlı repository secret oluşturun. OpenRouter kullanıyorsanız `OPENROUTER_API_KEY` ekleyin.
2. `pr_inceleme/`, `action.yml` ve örnek `.github/workflows/pr-inceleme.yml` dosyasını aynı yollarla hedef deponun taban dalına kopyalayın.
3. Bir pull request açın. Workflow açılışta, yeni commit gönderildiğinde ve PR yeniden açıldığında çalışır.

İki anahtar da varsa Anthropic seçilir. Varsayılan modeller [Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview) (`claude-sonnet-5-5`) ve [OpenRouter Claude Haiku 5.5](https://openrouter.ai/anthropic/claude-haiku-5.5) (`anthropic/claude-haiku-5.5`). Modeli değiştirmek için Actions repository variable olarak `PR_INCELEME_MODEL` ayarlayın.

## Yerel kullanım

`.env.example` içindeki değişkenleri kabuğunuzda tanımlayın. CLI değişkenleri süreç ortamından okur. GitHub üzerinden diff çekmek için `GITHUB_TOKEN` gerekir. Yerel dosya ve stdin kullanımı GitHub tokenı gerektirmez.

```bash
python3 -m pr_inceleme --diff dosya.diff
git diff main | python3 -m pr_inceleme --stdin
python3 -m pr_inceleme --repo owner/name --pr 42
python3 -m pr_inceleme --repo owner/name --pr 42 --post
```

Rapor stdout'a, durum mesajları stderr'e yazılır. `--post` verilmediğinde GitHub'a yazılmaz. Bu kullanım da model isteği yapar. `--budget 30000` ile varsayılan 60.000 karakterlik diff bütçesini değiştirebilirsiniz.

## Örnek çıktı

> # PR İnceleme Raporu
>
> ## Özet
>
> Kayıt formu, girilen e-posta adresini doğrulama servisine aktarıyor.
>
> ## Değişikliğin akışı
>
> - Form e-posta girdisini alıyor.
> - Doğrulama servisi adres biçimini kontrol ediyor.
> - Form doğrulama sonucunu kullanıcıya gösteriyor.
>
> ## Bulgular
>
> **🟠 Önemli · Boş e-posta kabul ediliyor** (kayit.py, satır 18)
>
> Boş değer doğrulamadan geçiyor ve kullanıcı kaydı eksik veriyle oluşabiliyor.
>
> **Öneri** Kayıt çağrısından önce boş e-posta değerini reddedin.
>
> ## Sorular
>
> - E-posta alanı zorunlu mu?
>
> ## Test önerileri
>
> - Boş e-posta ile kayıt isteğinin reddedildiğini doğrulayın.
>
> Bu otomatik bir incelemedir; onay ekip liderindedir.

## Maliyet ve güvenlik

- Sağlayıcılar giriş ve çıkış tokenlarına göre ücret alabilir. Ücret PR boyutuna, modele ve inceleme sayısına bağlıdır. GitHub'a yazmayan denemeler de model çağrısı yaptığında ücret doğurabilir.
- Örnek workflow `contents: read` ve `pull-requests: write` ister. Yerel token için ilgili depoda işlemle uyumlu Pull requests yetkisini kullanın. Workflow, action ve Python kodunu PR başından çalıştırmaz, taban commit'inden alır.
- Örnek workflow `pull_request` olayıyla çalışır. Model secret'ları bulunmayan fork PR'ları açıklayıcı bir bildirimle atlanır. GitHub ayarları fork workflow'unun başlaması için onay isteyebilir ve fork tokenını salt okunur tutabilir.
- PR başlığı, açıklaması ve diff model girdisidir. Ayrı güvenilmeyen veri etiketleri içindedir ve sistem talimatı bu içerikteki komutları yok saymasını ister. Prompt injection riski devam eder. Bot PR kodunu çalıştırmaz. Satır konumlarını ve diyagramdaki dosya adlarını diff ile doğrular.
- Seçilen diff ve kırpılmış PR metni model sağlayıcısına gider. Bu nedenle PR'a gizli bilgi koymayın. API anahtarlarını yalnızca secret veya ortam değişkeni olarak verin.

## Sınırlamalar

- Bot diffteki bağlamı görür. Depoyu taramaz ve test çalıştırmaz. Üretilmiş dosyalar, kilit dosyaları ve ikililer atlanır. Bütçe dolduğunda kaynak dosyaları belgelere, daha çok değişen dosyalar aynı gruptaki daha az değişen dosyalara göre önce seçilir. Sığmayan dosya bütünüyle atlanır ve raporda gösterilir.
- Satır yorumları yeni dosyadaki eklenen satırlara yazılır. Silinen satırlara ilişkin bulgular genel bulgu olarak gösterilir. GitHub inline incelemeyi HTTP 422 ile reddederse bot bulguları inceleme gövdesine taşır.
- Bot aynı commit'i gizli işaretleyici ve commit SHA'sıyla tanır. Örnek workflow aynı PR için çalışmaları sıraya alır. Bağımsız ve eşzamanlı yerel gönderimlerde GitHub atomik tekilleştirme sağlamaz.
- Mermaid diyagramı yalnızca model seçilen dosyalar arasında geçerli ilişkiler bildirmişse eklenir. Terminalde Markdown kaynak metni görünür.

## Testler

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```
