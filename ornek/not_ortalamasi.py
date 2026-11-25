def ortalama(notlar):
    toplam = 0
    for n in notlar:
        toplam += n
    return toplam / len(notlar)


def harf_notu(puan):
    if puan > 90:
        return "AA"
    elif puan > 80:
        return "BA"
    elif puan > 70:
        return "BB"
    return "FF"
