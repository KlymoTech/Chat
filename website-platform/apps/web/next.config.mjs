const target=process.env.API_INTERNAL_URL || 'http://localhost:4100';
export default {
 async rewrites(){return [{source:'/api/:path*',destination:target+'/:path*'}];},
 async headers(){return [{
   source:'/(.*)',
   headers:[
    {key:'X-Content-Type-Options',value:'nosniff'},
    {key:'Referrer-Policy',value:'strict-origin-when-cross-origin'},
    {key:'X-Frame-Options',value:'DENY'},
    {key:'Permissions-Policy',value:'geolocation=(), microphone=(), camera=()'}
   ]
 }];}
};
