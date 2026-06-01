const dict = {
    uz: {
        hero_title_1: "O'zbekistonliklar uchun",
        hero_title_2: "rus tili darsligi",
        hero_subtitle: "A2 darajasi uchun 30 ta mavzu: o'zbek tilidagi tarjimalar bilan amaliyotga ishonchli o'tish",
        btn_buy: "Telegram orqali sotib olish",
        btn_toc: "Mundarija",
        
        features_title: "Nega aynan StartRus?",
        features_subtitle: "Rus tilini tez va oson o'rganish uchun barcha qulayliklar",
        f1_title: "30 ta o'ylangan mavzu",
        f1_desc: "Salomlashish, do'kon, ish, oila va hayotiy vaziyatlar uchun eng kerakli mavzular.",
        f2_title: "O'zbek tiliga tarjima",
        f2_desc: "Barcha so'zlar va iboralar o'zbek tiliga aniq tarjima qilingan, lug'at qidirishga hojat yo'q.",
        f3_title: "Qulay Grammatika",
        f3_desc: "Qoidalar murakkab matnlar emas, balki tushunarli jadvallar va chizmalar orqali berilgan.",
        f4_title: "Dialoglar va Mashqlar",
        f4_desc: "Har bir mavzuni mustahkamlash uchun hayotiy dialoglar va amaliy mashqlar.",
        f5_title: "Mini-ma'lumotnoma",
        f5_desc: "Kelishiklar, zamonlar va boshqa qoidalar uchun qulay grammatik qo'llanma.",
        f6_title: "Qulay format",
        f6_desc: "Kompyuter yoki telefondan o'qish uchun moslashtirilgan zamonaviy dizayn.",
        
        audience_title: "A2 darajasi kimlar uchun?",
        audience_subtitle: "O'zingizga mos kelishini tekshiring",
        aud1: "Noldan boshlayotganlar uchun",
        aud2: "Bilimlarini yangilashni xohlaydiganlar uchun",
        aud3: "Ko'chib o'tayotgan yoki rus tilli mijozlar bilan ishlaydiganlar uchun",
        
        toc_title: "Kitob Mundarijasi",
        toc_subtitle: "Nimani o'rganasiz?",
        
        cta_title: "O'rganishni hoziroq boshlang!",
        cta_desc: "Telegram orqali osongina xarid qiling va o'z bilimingizni oshiring.",
        btn_buy_cta: "Telegram-bot orqali sotib olish",
        footer_rights: "Barcha huquqlar himoyalangan.",
        
        toc_items: [
            "Salomlashish va tanishuv",
            "Oila va qarindoshlar",
            "Mening uyim",
            "Do'konda xarid qilish",
            "Kundalik rejim",
            "Bo'sh vaqt va qiziqishlar",
            "Restoran va kafeda",
            "Sog'liq va kasalxona",
            "Sayohat va transport",
            "Kasblar va ish",
            "Ob-havo va fasllar",
            "Taklif etish va rad etish"
        ]
    },
    ru: {
        hero_title_1: "Учебник русского языка",
        hero_title_2: "для узбекистанцев",
        hero_subtitle: "30 тем для уровня A2 с уверенным переходом к практике и переводом на узбекский",
        btn_buy: "Купить через Telegram",
        btn_toc: "Оглавление",
        
        features_title: "Почему именно StartRus?",
        features_subtitle: "Все удобства для быстрого и легкого изучения русского языка",
        f1_title: "30 продуманных тем",
        f1_desc: "Приветствия, магазин, работа, семья и другие полезные темы для жизни.",
        f2_title: "Перевод на узбекский",
        f2_desc: "Все слова и фразы точно переведены на узбекский язык, не нужно искать в словаре.",
        f3_title: "Удобная грамматика",
        f3_desc: "Грамматика объясняется не сложными текстами, а через понятные таблицы и схемы.",
        f4_title: "Диалоги и упражнения",
        f4_desc: "Жизненные диалоги и практические упражнения для закрепления каждой темы.",
        f5_title: "Мини-справочник",
        f5_desc: "Удобный грамматический справочник для падежей, времен и других правил.",
        f6_title: "Удобный формат",
        f6_desc: "Современный дизайн, адаптированный для чтения с компьютера или телефона.",
        
        audience_title: "Для кого подходит A2?",
        audience_subtitle: "Проверьте, подходит ли это вам",
        aud1: "Для тех, кто начинает с нуля",
        aud2: "Для тех, кто хочет освежить знания",
        aud3: "Для тех, кто переезжает или работает с русскоязычными клиентами",
        
        toc_title: "Оглавление книги",
        toc_subtitle: "Что вы изучите?",
        
        cta_title: "Начните обучение прямо сейчас!",
        cta_desc: "Легко совершите покупку через Telegram и улучшайте свои знания.",
        btn_buy_cta: "Купить через Telegram-бота",
        footer_rights: "Все права защищены.",
        
        toc_items: [
            "Приветствие и знакомство",
            "Семья и родственники",
            "Мой дом",
            "Покупки в магазине",
            "Распорядок дня",
            "Свободное время и хобби",
            "В ресторане и кафе",
            "Здоровье и больница",
            "Путешествия и транспорт",
            "Профессии и работа",
            "Погода и времена года",
            "Приглашение и отказ"
        ]
    }
};

document.addEventListener('DOMContentLoaded', () => {
    // Current Language Setup
    let currentLang = 'uz'; // Default language

    const langToggle = document.getElementById('langToggle');
    const langBtns = document.querySelectorAll('.lang-btn');
    const elementsToTranslate = document.querySelectorAll('[data-i18n]');
    const tocList = document.getElementById('tocList');
    
    // Header Scroll Effect
    const header = document.getElementById('header');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            header.style.boxShadow = '0 10px 20px rgba(21, 101, 192, 0.12)';
            header.style.padding = '12px 0';
        } else {
            header.style.boxShadow = '0 4px 6px rgba(21, 101, 192, 0.08)';
            header.style.padding = '16px 0';
        }
    });

    // Populate TOC initially
    renderTOC();

    // Language Toggle Listener
    langBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const targetLang = e.target.getAttribute('data-target');
            if (currentLang === targetLang) return;
            
            // Update UI State
            langBtns.forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            langToggle.setAttribute('data-lang', targetLang);
            document.documentElement.lang = targetLang;
            
            // Switch Language
            currentLang = targetLang;
            translatePage();
            renderTOC();
        });
    });

    function translatePage() {
        elementsToTranslate.forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (dict[currentLang][key]) {
                el.innerHTML = dict[currentLang][key];
            }
        });
    }

    function renderTOC() {
        tocList.innerHTML = '';
        const items = dict[currentLang].toc_items;
        
        items.forEach((item, index) => {
            const num = index + 1;
            const div = document.createElement('div');
            div.className = 'toc-item';
            div.innerHTML = `
                <div class="toc-number">${num}</div>
                <div class="toc-title">${item}</div>
            `;
            tocList.appendChild(div);
        });
    }

    // Set Current Year in Footer
    const yearEl = document.getElementById('year');
    if (yearEl) {
        yearEl.textContent = new Date().getFullYear();
    }
});
