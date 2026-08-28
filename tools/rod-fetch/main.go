package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/go-rod/rod"
	"github.com/go-rod/rod/lib/launcher"
)

func main() {
	target := flag.String("url", "", "public page URL to fetch")
	userAgent := flag.String("user-agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36", "browser user agent")
	chromeBin := flag.String("chrome-bin", os.Getenv("CHROME_BIN"), "Chromium/Chrome executable")
	settle := flag.Duration("settle", 5*time.Second, "extra render settle time")
	flag.Parse()

	if *target == "" {
		log.Fatal("--url is required")
	}

	l := launcher.New().Headless(true).NoSandbox(true).Leakless(false)
	if *chromeBin != "" {
		l = l.Bin(*chromeBin)
	}
	l = l.Set("user-agent", *userAgent)
	l = l.Set("lang", "en-US")
	l = l.Set("window-size", "1440,1000")

	controlURL, err := l.Launch()
	if err != nil {
		log.Fatalf("launch chromium: %v", err)
	}

	browser := rod.New().ControlURL(controlURL)
	if err := browser.Connect(); err != nil {
		log.Fatalf("connect chromium: %v", err)
	}
	defer func() { _ = browser.Close() }()

	page := browser.MustPage(*target)
	page.MustWaitLoad()
	if *settle > 0 {
		time.Sleep(*settle)
	}
	// Trigger ordinary lazy/hydrated content that appears after the initial viewport.
	_, _ = page.Eval(`() => window.scrollTo(0, Math.min(document.body.scrollHeight, 2400))`)
	time.Sleep(750 * time.Millisecond)

	html, err := page.HTML()
	if err != nil {
		log.Fatalf("read html: %v", err)
	}
	fmt.Print(html)
}
