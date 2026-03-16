import { ArrowLeft } from 'lucide-react'

function Privacy() {
  return (
    <div className="min-h-screen p-4">
      <div className="max-w-4xl mx-auto">
        <a href="/" className="inline-flex items-center gap-2 text-primary-600 hover:text-primary-700 mb-6">
          <ArrowLeft className="w-4 h-4" />
          Back to StreamBuddy
        </a>

        <div className="card">
          <h1 className="text-3xl font-bold mb-6">Privacy Policy</h1>
          <div className="prose prose-slate max-w-none space-y-6 text-sm">
            <p className="text-gray-600">Last updated: March 16, 2026</p>

            <section>
              <h2 className="text-xl font-semibold mb-3">1. Information We Collect</h2>
              
              <h3 className="text-lg font-medium mb-2">1.1 Information You Provide</h3>
              <ul className="list-disc pl-6 space-y-2">
                <li><strong>YouTube Account:</strong> When you connect your YouTube account, we access your YouTube Live chat data</li>
                <li><strong>Audio Data:</strong> Microphone audio captured during streaming sessions (processed in real-time, not stored)</li>
              </ul>

              <h3 className="text-lg font-medium mb-2 mt-4">1.2 Automatically Collected Information</h3>
              <ul className="list-disc pl-6 space-y-2">
                <li><strong>Usage Data:</strong> Session duration, feature usage, error logs</li>
              </ul>
            </section>

            <section>
              <h2 className="text-xl font-semibold mb-3">2. How We Use Your Information</h2>
              <p>We use collected information to:</p>
              <ul className="list-disc pl-6 space-y-2">
                <li>Provide AI co-host functionality during your live streams</li>
                <li>Process YouTube Live chat messages and generate contextual responses</li>
                <li>Maintain session state and user preferences</li>
                <li>Improve the Service and fix technical issues</li>
                <li>Comply with legal obligations</li>
              </ul>
            </section>

            <section>
              <h2 className="text-xl font-semibold mb-3">3. Data Storage and Security</h2>
              
              <h3 className="text-lg font-medium mb-2">3.1 Storage</h3>
              <ul className="list-disc pl-6 space-y-2">
                <li><strong>YouTube Tokens:</strong> Stored securely on our backend servers</li>
                <li><strong>Session Data:</strong> Stored in your browser only</li>
                <li><strong>Audio Data:</strong> Processed in real-time, not stored</li>
                <li><strong>Chat Data:</strong> Temporarily cached during active sessions only</li>
              </ul>

              <h3 className="text-lg font-medium mb-2 mt-4">3.2 Security</h3>
              <p>
                We implement industry-standard security measures including HTTPS encryption and OAuth 2.0 authentication. 
                However, no method of transmission over the internet is 100% secure.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold mb-3">4. Third-Party Services</h2>
              <p>StreamBuddy integrates with the following third-party services:</p>
              <ul className="list-disc pl-6 space-y-2">
                <li><strong>Google Gemini Live API:</strong> Processes audio and chat data to generate AI responses</li>
                <li><strong>YouTube Data API v3:</strong> Accesses your YouTube Live chat messages</li>
              </ul>
              <p className="mt-2">
                These services have their own privacy policies. We recommend reviewing:
              </p>
              <ul className="list-disc pl-6 space-y-1">
                <li><a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">Google Privacy Policy</a></li>
              </ul>
            </section>

            <section>
              <h2 className="text-xl font-semibold mb-3">5. Data Retention</h2>
              <p>
                We retain data only as long as necessary to provide the Service:
              </p>
              <ul className="list-disc pl-6 space-y-2">
                <li><strong>Session Data:</strong> Deleted when you clear browser data</li>
                <li><strong>YouTube Tokens:</strong> Stored until you disconnect your account</li>
                <li><strong>Audio Data:</strong> Not stored, processed in real-time only</li>
                <li><strong>Logs:</strong> Retained for 30 days for debugging purposes</li>
              </ul>
            </section>

            <section>
              <h2 className="text-xl font-semibold mb-3">6. Your Rights</h2>
              <p>You have the right to:</p>
              <ul className="list-disc pl-6 space-y-2">
                <li><strong>Access:</strong> Request information about data we collect</li>
                <li><strong>Deletion:</strong> Clear your browser data to remove session information</li>
                <li><strong>Revoke Access:</strong> Disconnect your YouTube account at any time through Google Account settings</li>
                <li><strong>Opt-Out:</strong> Stop using the Service to cease data collection</li>
              </ul>
            </section>

            <section>
              <h2 className="text-xl font-semibold mb-3">7. Children's Privacy</h2>
              <p>
                StreamBuddy is not intended for users under 13 years of age. We do not knowingly collect personal 
                information from children under 13.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold mb-3">8. Changes to Privacy Policy</h2>
              <p>
                We may update this Privacy Policy from time to time. We will notify users of significant changes 
                by updating the "Last updated" date at the top of this policy.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold mb-3">9. Contact Us</h2>
              <p>
                For questions about this Privacy Policy or our data practices, please contact us at{' '}
                <a href="mailto:acedev02@gmail.com" className="text-primary-600 hover:underline">
                  acedev02@gmail.com
                </a>
              </p>
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Privacy
