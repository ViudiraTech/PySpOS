document.addEventListener('DOMContentLoaded', function() {
    const themeToggle = document.getElementById('theme-toggle');
    const body = document.body;
    const storageKey = 'theme';

    const readTheme = () => {
        try {
            return localStorage.getItem(storageKey);
        } catch (error) {
            return null;
        }
    };

    const saveTheme = (theme) => {
        try {
            localStorage.setItem(storageKey, theme);
        } catch (error) {
            return;
        }
    };

    const preferredTheme = () => {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
            return 'light';
        }
        return 'dark';
    };

    const applyTheme = (theme, persist = false) => {
        const normalized = theme === 'light' ? 'light' : 'dark';
        const isLight = normalized === 'light';
        body.classList.toggle('light-theme', isLight);
        document.documentElement.dataset.theme = normalized;
        if (themeToggle) {
            themeToggle.setAttribute('aria-pressed', String(isLight));
            themeToggle.setAttribute('aria-label', isLight ? '切换到暗色主题' : '切换到亮色主题');
            const icon = themeToggle.querySelector('i');
            if (icon) {
                icon.className = isLight ? 'far fa-sun' : 'far fa-moon';
            }
        }
        if (persist) {
            saveTheme(normalized);
        }
    };

    const savedTheme = readTheme();
    applyTheme(savedTheme || preferredTheme(), !savedTheme);

    if (themeToggle) {
        themeToggle.setAttribute('role', 'button');
        themeToggle.setAttribute('tabindex', '0');
        const toggleTheme = () => {
            const icon = themeToggle.querySelector('i');
            const nextTheme = body.classList.contains('light-theme') ? 'dark' : 'light';
            if (icon) {
                icon.classList.add('icon-transition');
                window.setTimeout(() => {
                    applyTheme(nextTheme, true);
                    icon.classList.remove('icon-transition');
                }, 150);
            } else {
                applyTheme(nextTheme, true);
            }
        };
        themeToggle.addEventListener('click', toggleTheme);
        themeToggle.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                toggleTheme();
            }
        });
    }

    window.addEventListener('storage', (event) => {
        if (event.key === storageKey || event.key === null) {
            applyTheme(event.newValue || preferredTheme());
        }
    });
    
    // Mobile Navigation Toggle
    const navToggle = document.getElementById('nav-toggle');
    const navMenu = document.getElementById('nav-menu');
    const navLinks = document.querySelectorAll('.nav-link');
    const navIndicator = document.getElementById('nav-indicator');

    if (navToggle && navMenu) {
        navToggle.addEventListener('click', function() {
            const isActive = navMenu.classList.toggle('active');
            if (isActive) {
                navToggle.classList.add('active');
                body.style.overflow = 'hidden';
            } else {
                navToggle.classList.remove('active');
                body.style.overflow = '';
            }
        });
    }

    // Navigation Link Active State
    if (navLinks.length > 0) {
        navLinks.forEach(link => {
            link.addEventListener('click', function() {
                navLinks.forEach(l => l.classList.remove('active'));
                this.classList.add('active');
                
                // 在移动端点击链接后关闭菜单
                if (navMenu.classList.contains('active')) {
                    navMenu.classList.remove('active');
                    navToggle.classList.remove('active');
                    body.style.overflow = '';
                }
            });
        });
    }

    // Navigation Indicator (Desktop only)
    if (navIndicator && window.innerWidth > 768) {
        const updateIndicator = (element) => {
            if (!element) return;
            const rect = element.getBoundingClientRect();
            const parentRect = element.parentElement.getBoundingClientRect();
            navIndicator.style.transform = `translateX(${rect.left - parentRect.left}px)`;
            navIndicator.style.width = `${rect.width}px`;
        };

        navLinks.forEach(link => {
            link.addEventListener('mouseenter', () => updateIndicator(link));
        });

        // Initialize with active link
        const activeLink = document.querySelector('.nav-link.active');
        if (activeLink) {
            updateIndicator(activeLink);
        }

        // Update on window resize
        let resizeTimer;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                if (window.innerWidth <= 768) {
                    navIndicator.style.display = 'none';
                } else {
                    navIndicator.style.display = 'block';
                    updateIndicator(activeLink);
                }
            }, 250);
        });
    }

    // Smooth Scroll for Buttons
    const heroButtons = document.querySelectorAll('.btn');
    heroButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            if (href && href.startsWith('#')) {
                e.preventDefault();
                const target = document.querySelector(href);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
        });
    });

    // Scroll-based Header Shadow
    let ticking = false;
    window.addEventListener('scroll', function() {
        if (!ticking) {
            window.requestAnimationFrame(() => {
                const header = document.querySelector('header');
                if (header) {
                    const scrollPosition = window.scrollY;
                    header.style.boxShadow = scrollPosition > 100 
                        ? '0 4px 30px rgba(0, 0, 0, 0.5)' 
                        : '0 4px 30px rgba(0, 0, 0, 0.3)';
                }
                ticking = false;
            });
            ticking = true;
        }
    });

    // Footer Logo Click to Top
    const footerLogo = document.querySelector('.footer-logo');
    if (footerLogo) {
        footerLogo.addEventListener('click', function() {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    // Close mobile menu when clicking outside
    document.addEventListener('click', function(e) {
        if (navMenu && navMenu.classList.contains('active')) {
            if (!navMenu.contains(e.target) && !navToggle.contains(e.target)) {
                navMenu.classList.remove('active');
                navToggle.classList.remove('active');
                body.style.overflow = '';
            }
        }
    });

    // 毛玻璃效果通过 CSS 的 backdrop-filter 实现，无需额外 JavaScript
});
