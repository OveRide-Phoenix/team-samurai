import { useState } from 'react';
import { Renderer, type Library } from '@openuidev/react-lang';

function Surface({ response, library }: { response: string; library: Library }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <p className="error-note" role="alert">This view could not be displayed. Ask Samurai to revise it.</p>;
  return <Renderer.Root response={response} library={library} isStreaming={false} onError={errors => setFailed(errors.length > 0)}><Renderer.Content style={{ display: 'contents' }} /></Renderer.Root>;
}
export function OpenUIRender(props: { response: string; library: Library }) {
  return <Surface key={props.response} {...props} />;
}
