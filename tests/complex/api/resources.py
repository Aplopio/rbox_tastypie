from builtins import object
from django.contrib.auth.models import User, Group
from django.contrib.comments.models import Comment
from tastypie.fields import CharField, ForeignKey, ManyToManyField, OneToOneField, OneToManyField
from tastypie.resources import ModelResource
from complex.models import Post, Profile


class ProfileResource(ModelResource):
    class Meta(object):
        queryset = Profile.objects.all()
        resource_name = 'profiles'


class CommentResource(ModelResource):
    class Meta(object):
        queryset = Comment.objects.all()
        resource_name = 'comments'


class GroupResource(ModelResource):
    class Meta(object):
        queryset = Group.objects.all()
        resource_name = 'groups'


class UserResource(ModelResource):
    groups = ManyToManyField(GroupResource, 'groups', full=True)
    profile = OneToOneField(ProfileResource, 'profile', full=True)
    
    class Meta(object):
        queryset = User.objects.all()
        resource_name = 'users'


class PostResource(ModelResource):
    user = ForeignKey(UserResource, 'user')
    comments = OneToManyField(CommentResource, 'comments', full=False)
    
    class Meta(object):
        queryset = Post.objects.all()
        resource_name = 'posts'
