// Neuro Search extension — community platform adapters for "Scan this community" (S93).
//
// An adapter is DATA about a platform's own API, read from the person's logged-in tab with their session cookie:
// how to page the feed, how to page a post's comments, and how to turn each answer into the platform-neutral
// `community_thread_capture/1` contract the app stores (neurosearch/community.py: thread_from_generic_capture).
// The walker in background.js is the same for every platform; only this file knows smbmarket.com.
//
// Shared by the popup (to know whether the current tab is a community it can scan) and the background worker
// (importScripts). Scoped, like thread-capture.js: nothing here leaks into the global scope of either.
(() => {
  const SMB = {
    key: 'smbmarket',
    platform: 'smbmarket',
    label: 'SMB Market',
    match: url => /^https:\/\/(www\.)?smbmarket\.com\/dashboard\/community(\/|$|\?)/.test(url || ''),
    // the feed, newest first, 50 per page; `cursor` comes back from the previous page (null = first page)
    feedUrl: cursor => 'https://community-api.smbmarket.com/api/v1/feed?kind=latest&limit=50' + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''),
    parseFeed: json => ({
      items: (json && json.items || []).map(p => ({
        id: p.id, title: p.title || '', body: p.body || '', author: p.author && (p.author.displayName || p.author.handle) || null,
        created_at: p.createdAt, edited: !!p.editedAt, score: p.likeCount, expected_comments: p.commentCount, space: p.space || '',
        kind: p.kind, url: `https://smbmarket.com/dashboard/community/post/${p.id}/`,
      })),
      next: json && json.nextCursor || null,
    }),
    commentsUrl: (postId, cursor) => `https://community-api.smbmarket.com/api/v1/posts/${postId}/comments?limit=50` + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''),
    parseComments: (json, post) => ({
      items: (json && json.items || []).map(c => ({
        id: c.id, parent_id: c.parentId || null, author: c.author && (c.author.displayName || c.author.handle) || null, text: c.body || '',
        score: c.likeCount, created_at: c.createdAt, edited: !!c.editedAt, deleted: false, permalink: post.url + '#' + c.id,
      })),
      next: json && json.nextCursor || null,
    }),
    community: post => 'SMB Market' + (post.space ? ' · ' + post.space : ''),
  };
  const ADAPTERS = [SMB];
  self.NSCommunityAdapters = {
    all: ADAPTERS,
    forUrl: url => ADAPTERS.find(a => a.match(url)) || null,
    // one thread in the app's contract
    contract: (adapter, post, comments, partial) => ({
      contract: 'community_thread_capture/1', platform: adapter.platform, community: adapter.community(post),
      thread: { id: post.id, title: post.title, author: post.author, body: post.body, created_at: post.created_at, score: post.score, url: post.url,
                expected_comments: post.expected_comments, edited: post.edited, deleted: false },
      comments,
      capture: { status: partial ? 'partial' : (post.expected_comments == null ? 'unknown' : (comments.length >= post.expected_comments ? 'complete' : 'partial')),
                 captured: comments.length, expected: post.expected_comments, method: 'community api' },
    }),
  };
})();
