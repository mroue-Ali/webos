import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './App.tsx'
import { ApiError } from './api/client'
import { keys } from './api/queries'
import './index.css'

// A 401 while signed in means the session ended: re-check /me, which sends the app back to
// the login form. While signed out (say, a wrong password) there is nothing to re-check.
function onError(error: Error) {
  const signedIn = queryClient.getQueryState(keys.me)?.status === 'success'
  if (signedIn && error instanceof ApiError && error.status === 401) {
    void queryClient.invalidateQueries({ queryKey: keys.me })
  }
}

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.queryKey[0] !== keys.me[0]) onError(error)
    },
  }),
  mutationCache: new MutationCache({ onError }),
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
