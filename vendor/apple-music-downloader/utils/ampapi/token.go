package ampapi

import (
	"errors"
	"io"
	"net/http"
	"regexp"
)

func GetToken() (string, error) {
	req, err := http.NewRequest("GET", "https://music.apple.com", nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	regex := regexp.MustCompile(`/assets/index[^"]+\.js`)
	indexJsUri := regex.FindString(string(body))
	if indexJsUri == "" {
		return "", errors.New("cannot find index js in html")
	}

	req, err = http.NewRequest("GET", "https://music.apple.com"+indexJsUri, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, err = io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	tokenRegex := regexp.MustCompile(`"(eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)"`)
	matches := tokenRegex.FindStringSubmatch(string(body))
	if len(matches) > 1 {
		return matches[1], nil
	}

	// Fallback to eyJh
	fallbackRegex := regexp.MustCompile(`eyJh([^"]*)`)
	token := fallbackRegex.FindString(string(body))
	if token != "" {
		return token, nil
	}

	return "", errors.New("cannot extract token from js")
}
