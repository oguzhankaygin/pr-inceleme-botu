# Öğrenci Takımı için PR İnceleme Botu

Bot, pull request diffini Claude ile inceler. Türkçe özet, gerekçeli bulgular ve test önerileri üretir. GitHub'a yalnızca `COMMENT` incelemesi gönderir. Son karar ekip liderindedir. Python 3.10+ ve standart kütüphane yeterlidir.

## GitHub Actions kurulumu

1. Hedef deponun **Settings → Secrets and variables → Actions** bölümünde `ANTHROPIC_API_KEY` adlı repository secret oluşturun. OpenRouter kullanıyorsanız `OPENROUTER_API_KEY` ekleyin.
2. Aşağıdaki workflow'u hedef deponun `.github/workflows/pr-inceleme.yml` yoluna ekleyin. Action kendi dizininden çalışır ve PR bilgisiyle diffi GitHub API üzerinden alır. Hedef depo için checkout gerekmez.
3. Bir pull request açın. Bot uygun PR'lara Türkçe bir inceleme gönderir.

```yaml
name: Türkçe PR incelemesi

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, labeled]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: pr-inceleme-${{ github.event.pull_request.number }}
  cancel-in-progress: false

jobs:
  inceleme:
    runs-on: ubuntu-latest
    steps:
      - name: İncele
        uses: oguzhankaygin/pr-inceleme-botu@v1
        with:
          github-token: ${{ github.token }}
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          openrouter-api-key: ${{ secrets.OPENROUTER_API_KEY }}
          model: ${{ vars.PR_INCELEME_MODEL }}
          tetikleme: otomatik
```

- `tetikleme: otomatik` varsayılandır. PR açıldığında, yeni commit gönderildiğinde, PR yeniden açıldığında veya incelemeye hazır olduğunda bot devreye girer. Yalnızca bu modu kullanacaksanız `labeled` olayını listeden çıkarabilirsiniz.
- `tetikleme: etiket` seçeneğinde aynı olaylar yalnızca PR'da `claude-inceleme` etiketi varsa inceleme başlatır. Etiketi eklemek de incelemeyi tetikler. Workflow'da `labeled` olayını tutun.
- Taslak PR'lar, yalnızca test, doküman veya kilit dosyası değişen diff'ler ve eklenen ile silinen satırların toplamı üçten küçük olan diff'ler loga yazılıp atlanır. Aynı commit için mevcut bot yorumu varsa yeni inceleme yapılmaz.
- İki anahtar da varsa Anthropic seçilir. Varsayılan model Anthropic'te `claude-haiku-5-5`, OpenRouter'da `anthropic/claude-haiku-5.5`. Modeli değiştirmek için `PR_INCELEME_MODEL` adlı Actions repository variable tanımlayın. [Anthropic model bilgileri](https://platform.claude.com/docs/en/models/haiku-5-5/overview), [OpenRouter model bilgileri](https://openrouter.ai/anthropic/claude-haiku-5.5).

Kodu kendi deponuzda tutmayı tercih ederseniz `pr_inceleme/` ve `action.yml` dosyalarını taban dalına kopyalayın. Workflow'da güvenilir taban commit'ini `actions/checkout@v4` ile alın (`ref: ${{ github.event.pull_request.base.sha }}`, `persist-credentials: false`) ve inceleme adımında `uses: ./` kullanın.

## Yerel kullanım

`.env.example` içindeki değişkenleri kabuğunuzda tanımlayın. CLI değişkenleri süreç ortamından okur. GitHub üzerinden diff çekmek için `GITHUB_TOKEN` gerekir. Yerel dosya ve stdin kullanımı GitHub tokenı gerektirmez.

```bash
python3 -m pr_inceleme --diff dosya.diff
git diff main | python3 -m pr_inceleme --stdin
python3 -m pr_inceleme --repo owner/name --pr 42
python3 -m pr_inceleme --repo owner/name --pr 42 --post
```

Rapor stdout'a, durum mesajları stderr'e yazılır. `--post` verilmediğinde GitHub'a yazılmaz. İncelemeye uygun diff için bu kullanım da model isteği yapar. `--budget 30000` ile varsayılan 40.000 karakterlik diff bütçesini değiştirebilirsiniz.

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

## Öğrenciler için maliyet

Anthropic Claude Haiku 5.5 için 100.000 girdi tokenına kadar fiyat, milyon token başına girdi için 0,10 USD ve çıktı için 0,50 USD'dir. PR başına tek inceleme, 10.000 girdi tokenı (sistem talimatı, PR bilgileri ve seçilen diff dahil) ve 1.500 çıktı tokenı varsayarsak önbellek hariç tahmin **0,00175 USD** olur. [Anthropic fiyatlandırması](https://platform.claude.com/docs/en/about-claude/pricing).

```text
(10.000 × 0,10 + 1.500 × 0,50) / 1.000.000 = 0,00175 USD
```

Bir PR'ın toplam maliyeti, incelenen commit'lerin maliyetleri toplamıdır. Bot, fiyat tablosunda bulunan modeller için API'nin bildirdiği token kullanımından tahmini maliyeti hesaplar ve raporun altına ekler. Anthropic sistem talimatında geçici önbellek kullanır. Okuma ve yazma tokenları ayrı tarifelerden hesaplanır. [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

Ekip başına tek anahtar kullanın ve aylık harcama limiti koyun.

## Güvenlik

- Örnek workflow `contents: read` ve `pull-requests: write` ister. Yerel token için ilgili depoda işlemle uyumlu Pull requests yetkisini kullanın. Workflow, action kodunu `v1` referansından çalıştırır.
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
