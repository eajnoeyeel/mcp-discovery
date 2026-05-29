import { Link } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

export default function HostedConnectUnavailable() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-16">
      <Card>
        <CardHeader>
          <CardTitle>Hosted Connect is not available</CardTitle>
          <CardDescription>
            The browser-based connect flow is not enabled in this build. Use the standard
            registration form to finish adding your server; hosted connect will become
            available once the backend routes ship.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link to="/dashboard/register">Back to Register Server</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
