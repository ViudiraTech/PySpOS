(function() {
    const storageKey = 'theme';
    let savedTheme = null;
    try {
        savedTheme = localStorage.getItem(storageKey);
    } catch (error) {
        savedTheme = null;
    }
    const theme = savedTheme === 'light' || savedTheme === 'dark'
        ? savedTheme
        : (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches
            ? 'light'
            : 'dark');
    document.documentElement.dataset.theme = theme;
    if (document.body) {
        document.body.classList.toggle('light-theme', theme === 'light');
    }
})();
