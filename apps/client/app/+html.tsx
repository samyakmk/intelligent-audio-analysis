import { ScrollViewStyleReset } from 'expo-router/html';
import type { PropsWithChildren } from 'react';

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="theme-color" content="#f4f5ef" />
        <meta name="description" content="Evidence-grounded audio intelligence and cost architecture demo." />
        <ScrollViewStyleReset />
        <style dangerouslySetInnerHTML={{ __html: 'html,body,#root{height:100%;}body{margin:0;background:#F4F5EF;}*{box-sizing:border-box;}button,input,textarea{font:inherit;}' }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
