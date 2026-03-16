const Footer = () => {
  return (
    <footer className="mt-8 py-6 border-t border-gray-200">
      <div className="max-w-6xl mx-auto px-4">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-gray-600">
          <p>© 2026 StreamBuddy. Built for Gemini Live Agent Challenge.</p>
          <div className="flex items-center gap-6">
            <a 
              href="/terms" 
              className="hover:text-primary-600 transition-colors"
            >
              Terms of Service
            </a>
            <a 
              href="/privacy" 
              className="hover:text-primary-600 transition-colors"
            >
              Privacy Policy
            </a>
            <a 
              href="https://github.com/yaseen2402/StreamBuddy" 
              target="_blank" 
              rel="noopener noreferrer"
              className="hover:text-primary-600 transition-colors"
            >
              GitHub
            </a>
          </div>
        </div>
      </div>
    </footer>
  )
}

export default Footer
